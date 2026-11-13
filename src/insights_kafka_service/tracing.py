"""OpenTelemetry tracing watcher for the insights-core-messaging pipeline.

Creates custom spans for each phase of the rule evaluation workflow to
identify bottlenecks: archive download, extraction, analysis, and publishing.
"""

import logging

from opentelemetry import context, trace
from insights_messaging.watchers import ConsumerWatcher, EngineWatcher

from .telemetry import get_tracer, OTEL_ENABLED

logger = logging.getLogger(__name__)

_tracer = get_tracer("insights_kafka_service.engine")


class Watcher(ConsumerWatcher):
    """Creates spans for consumer-level events (recv, download, success/failure)."""

    def on_recv(self, msg):
        if not OTEL_ENABLED:
            return

        inventory_id = msg.host.get("id") if msg.host else None

        span = _tracer.start_span(
            "engine.receive_message",
            attributes={
                "host.inventory_id": inventory_id or "",
            },
        )
        span.end()

        self._download_span = _tracer.start_span(
            "engine.download_archive",
            kind=trace.SpanKind.CLIENT,
            attributes={
                "http.method": "GET",
            },
        )
        self._download_token = context.attach(
            trace.set_span_in_context(self._download_span)
        )

    def on_download(self, path):
        if not OTEL_ENABLED:
            return
        if hasattr(self, "_download_token"):
            context.detach(self._download_token)
            del self._download_token
        if hasattr(self, "_download_span"):
            self._download_span.set_attribute("archive.url", str(path))
            self._download_span.set_status(trace.StatusCode.OK)
            self._download_span.end()
            del self._download_span

    def on_process(self, input_msg, results):
        if not OTEL_ENABLED:
            return
        if hasattr(self, "_download_token"):
            context.detach(self._download_token)
            del self._download_token
        if hasattr(self, "_download_span"):
            self._download_span.set_status(trace.StatusCode.OK)
            self._download_span.end()
            del self._download_span

    def on_consumer_failure(self, input_msg, exception):
        if not OTEL_ENABLED:
            return

        if hasattr(self, "_download_token"):
            context.detach(self._download_token)
            del self._download_token
        if hasattr(self, "_download_span"):
            self._download_span.set_status(
                trace.StatusCode.ERROR, str(exception)
            )
            self._download_span.record_exception(exception)
            self._download_span.end()
            del self._download_span

        span = _tracer.start_span("engine.consumer_failure")
        span.set_status(trace.Status(trace.StatusCode.ERROR, str(exception)))
        span.record_exception(exception)
        span.end()


class Engine(EngineWatcher):
    """Creates spans for engine-level events (extraction, analysis)."""

    def pre_extract(self, broker, archive):
        if not OTEL_ENABLED:
            return
        self._extract_span = _tracer.start_span(
            "engine.extract_archive",
            attributes={"archive.path": str(archive)},
        )
        self._extract_token = context.attach(
            trace.set_span_in_context(self._extract_span)
        )

    def on_extract(self, ctx, broker, extraction):
        if not OTEL_ENABLED:
            return
        if hasattr(self, "_extract_token"):
            context.detach(self._extract_token)
            del self._extract_token
        if hasattr(self, "_extract_span"):
            self._extract_span.end()
            del self._extract_span

        self._analysis_span = _tracer.start_span("engine.rule_evaluation")
        self._analysis_token = context.attach(
            trace.set_span_in_context(self._analysis_span)
        )

    def on_engine_success(self, broker, result):
        if not OTEL_ENABLED:
            return
        if hasattr(self, "_analysis_token"):
            context.detach(self._analysis_token)
            del self._analysis_token
        if hasattr(self, "_analysis_span"):
            self._analysis_span.set_attribute("engine.result_count", len(result) if result else 0)
            self._analysis_span.end()
            del self._analysis_span

    def on_engine_failure(self, broker, ex):
        if not OTEL_ENABLED:
            return
        if hasattr(self, "_analysis_token"):
            context.detach(self._analysis_token)
            del self._analysis_token
        if hasattr(self, "_analysis_span"):
            self._analysis_span.set_status(trace.Status(trace.StatusCode.ERROR, str(ex)))
            self._analysis_span.record_exception(ex)
            self._analysis_span.end()
            del self._analysis_span

    def on_engine_complete(self, broker):
        if not OTEL_ENABLED:
            return
        for token_attr, span_attr in (
            ("_extract_token", "_extract_span"),
            ("_analysis_token", "_analysis_span"),
        ):
            token = getattr(self, token_attr, None)
            if token:
                context.detach(token)
                delattr(self, token_attr)
            span = getattr(self, span_attr, None)
            if span:
                span.end()
                delattr(self, span_attr)
