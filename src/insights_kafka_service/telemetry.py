"""OpenTelemetry initialization for the Insights Engine service.

Usage:
    from insights_kafka_service.telemetry import init_otel, instrument_kafka_producer, instrument_outbound_http

    # In app.py main():
    init_otel()

    # After producer creation:
    producer = instrument_kafka_producer(producer)

    # For outbound HTTP (archive downloads):
    instrument_outbound_http()
"""

import logging
import os
from threading import local

from opentelemetry import trace

logger = logging.getLogger(__name__)

threadctx = local()

OTEL_ENABLED = os.getenv("OTEL_ENABLED", "false").lower() == "true"
OTEL_HTTP_OUTBOUND_ENABLED = os.getenv("OTEL_HTTP_OUTBOUND_ENABLED", "true").lower() == "true"
OTEL_MQ_ENABLED = os.getenv("OTEL_MQ_ENABLED", "true").lower() == "true"

_RH_PROPAGATED_ATTRS = ("rh.org_id", "rh.request_id")

_otel_initialized = False


def _parse_sampling_rate() -> float:
    raw = os.getenv("OTEL_SAMPLING_RATE", "1.0")
    try:
        rate = float(raw)
    except ValueError:
        logger.warning("Invalid OTEL_SAMPLING_RATE=%r; falling back to 1.0", raw)
        rate = 1.0
    return min(max(rate, 0.0), 1.0)


def _build_rh_attribute_span_processor():
    """Build a SpanProcessor that sets rh.* attributes on every span.

    Sets rh.service on all spans and propagates rh.org_id / rh.request_id
    from parent spans to child spans, with fallback to thread-local context.
    """
    from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor

    class RHAttributeSpanProcessor(SpanProcessor):
        def on_start(self, span, parent_context=None):
            if not span or not span.is_recording():
                return

            span.set_attribute("rh.service", "insights-engine")

            parent = (
                trace.get_current_span(parent_context)
                if parent_context is not None
                else trace.get_current_span()
            )
            parent_attrs = {}
            if isinstance(parent, ReadableSpan) and parent.attributes:
                parent_attrs = parent.attributes

            for attr in _RH_PROPAGATED_ATTRS:
                if attr in (span.attributes or {}):
                    continue
                value = parent_attrs.get(attr)
                if value is None:
                    thread_key = "org_id" if attr == "rh.org_id" else "request_id"
                    value = getattr(threadctx, thread_key, None)
                if value is not None:
                    span.set_attribute(attr, value)

    return RHAttributeSpanProcessor()


def get_tracer(name: str):
    """Get an OpenTelemetry tracer for creating custom spans.

    When OTel is disabled, the SDK's default TracerProvider returns no-op spans.
    """
    return trace.get_tracer(name)


def init_otel(service_name="insights-engine", service_version=None):
    """Initialize OpenTelemetry tracing. Safe to call multiple times.

    Configures:
    - Resource with service.name and service.version (from IMAGE_TAG env var)
    - ParentBased(TraceIdRatioBased) sampler
    - OTLP/HTTP exporter with BatchSpanProcessor
    - RHAttributeSpanProcessor for rh.* span attributes
    """
    global _otel_initialized

    if _otel_initialized:
        return

    if not OTEL_ENABLED:
        logger.info("OpenTelemetry is disabled (OTEL_ENABLED != 'true')")
        _otel_initialized = True
        return

    from opentelemetry.exporter.otlp.proto.http import Compression
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
    from opentelemetry.sdk.trace import SpanLimits, TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    if service_version is None:
        service_version = os.getenv("IMAGE_TAG", "unknown")
    sampling_rate = _parse_sampling_rate()

    resource = Resource.create(
        attributes={
            SERVICE_NAME: service_name,
            SERVICE_VERSION: service_version,
            "deployment.environment": os.getenv("NAMESPACE", "development"),
        }
    )

    sampler = ParentBased(root=TraceIdRatioBased(sampling_rate))
    span_limits = SpanLimits(
        max_attributes=int(os.getenv("OTEL_SPAN_ATTRIBUTE_COUNT_LIMIT", "64")),
        max_attribute_length=int(os.getenv("OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT", "1024")),
    )
    provider = TracerProvider(resource=resource, sampler=sampler, span_limits=span_limits)

    provider.add_span_processor(_build_rh_attribute_span_processor())

    traces_exporter = os.getenv("OTEL_TRACES_EXPORTER", "otlp").lower()
    if traces_exporter != "none":
        compression_str = os.getenv("OTEL_EXPORTER_OTLP_COMPRESSION", "gzip").lower()
        compression_map = {"gzip": Compression.Gzip, "deflate": Compression.Deflate}
        compression = compression_map.get(compression_str, Compression.NoCompression)

        exporter = OTLPSpanExporter(compression=compression)
        provider.add_span_processor(
            BatchSpanProcessor(
                exporter,
                max_queue_size=int(os.getenv("OTEL_BSP_MAX_QUEUE_SIZE", "8192")),
                max_export_batch_size=int(os.getenv("OTEL_BSP_MAX_EXPORT_BATCH_SIZE", "256")),
                schedule_delay_millis=int(os.getenv("OTEL_BSP_SCHEDULE_DELAY", "2000")),
                export_timeout_millis=int(os.getenv("OTEL_BSP_EXPORT_TIMEOUT", "10000")),
            )
        )

    trace.set_tracer_provider(provider)
    _otel_initialized = True

    logger.info(
        "OpenTelemetry initialized: service=%s version=%s "
        "sampling=%.2f mq=%s http_outbound=%s exporter=%s",
        service_name,
        service_version,
        sampling_rate,
        OTEL_MQ_ENABLED,
        OTEL_HTTP_OUTBOUND_ENABLED,
        traces_exporter,
    )


def extract_context_from_headers(headers):
    """Extract W3C TraceContext from Kafka message headers.

    Returns an OTel Context with the propagated trace context, or None
    if no traceparent header is found.
    """
    if not OTEL_ENABLED or not OTEL_MQ_ENABLED or not headers:
        return None

    from opentelemetry.propagate import extract

    carrier = {}
    for key, value in headers:
        if key in ("traceparent", "tracestate"):
            carrier[key] = value.decode("utf-8") if isinstance(value, bytes) else value

    if not carrier:
        return None

    return extract(carrier)


def inject_context_into_headers(headers=None):
    """Inject W3C TraceContext into Kafka message headers for downstream propagation.

    Returns a list of (key, value) tuples suitable for confluent-kafka produce().
    """
    if not OTEL_ENABLED or not OTEL_MQ_ENABLED:
        return headers or []

    from opentelemetry.propagate import inject

    carrier = {}
    inject(carrier)

    result = list(headers) if headers else []
    for key, value in carrier.items():
        result.append((key, value.encode("utf-8") if isinstance(value, str) else value))

    return result


def instrument_kafka_producer(producer):
    """Wrap a confluent-kafka Producer with OTel instrumentation.

    Returns the instrumented producer, or the original if OTel/MQ is disabled.
    """
    if not OTEL_ENABLED or not OTEL_MQ_ENABLED:
        return producer

    try:
        from opentelemetry.instrumentation.confluent_kafka import ConfluentKafkaInstrumentor

        return ConfluentKafkaInstrumentor.instrument_producer(
            producer, tracer_provider=trace.get_tracer_provider()
        )
    except ImportError:
        logger.warning("confluent-kafka instrumentation unavailable; continuing without producer spans")
        return producer


def instrument_outbound_http():
    """Instrument outbound HTTP calls (archive downloads) with OpenTelemetry.

    Automatically creates spans for all requests made via the `requests` library,
    including trace context propagation to downstream services.
    """
    if not OTEL_ENABLED or not OTEL_HTTP_OUTBOUND_ENABLED:
        return

    try:
        from opentelemetry.instrumentation.requests import RequestsInstrumentor

        RequestsInstrumentor().instrument(request_hook=_outbound_request_hook)
        logger.info("Outbound HTTP (requests library) instrumented with OpenTelemetry")
    except ImportError:
        logger.warning("requests instrumentation unavailable; continuing without HTTP spans")


def _outbound_request_hook(span, request, *_args, **_kwargs):
    """Use METHOD + path as the client span name (default is METHOD only)."""
    if not span or not span.is_recording():
        return
    from urllib.parse import urlparse

    parsed = urlparse(request.path_url)
    path = parsed.path or "/"
    span.update_name(f"{request.method} {path}")
