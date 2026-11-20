"""Unit tests for OpenTelemetry instrumentation in insights-engine."""

import logging
import os
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def reset_otel():
    """Reset OpenTelemetry TracerProvider and internal state before and after each test."""
    from opentelemetry import trace
    import insights_kafka_service.telemetry as telemetry_mod

    def _cleanup():
        provider = trace.get_tracer_provider()
        if hasattr(provider, "shutdown"):
            try:
                provider.shutdown()
            except Exception:
                pass
        trace._TRACER_PROVIDER = None
        trace._TRACER_PROVIDER_SET_ONCE._done = False
        telemetry_mod._otel_initialized = False
        if hasattr(telemetry_mod, "threadctx"):
            telemetry_mod.threadctx.org_id = None
            telemetry_mod.threadctx.request_id = None

    _cleanup()
    yield
    _cleanup()


@pytest.fixture(autouse=True)
def mock_otlp_exporter():
    """Mock OTLPSpanExporter to avoid network calls to localhost:4318 during tests."""
    from opentelemetry.sdk.trace.export import SpanExportResult

    with patch("opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter") as mock_exp:
        mock_instance = MagicMock()
        mock_instance.export.return_value = SpanExportResult.SUCCESS
        mock_exp.return_value = mock_instance
        yield mock_exp


class TestTelemetryInit:
    """Tests for init_otel() initialization and toggle behavior."""

    @patch.dict(os.environ, {"OTEL_ENABLED": "false"})
    def test_otel_disabled_by_default(self):
        """OTel is disabled when OTEL_ENABLED is not 'true'."""
        import importlib
        import insights_kafka_service.telemetry as telemetry_mod

        importlib.reload(telemetry_mod)
        telemetry_mod._otel_initialized = False
        telemetry_mod.init_otel()
        assert telemetry_mod._otel_initialized is True

    @patch.dict(os.environ, {"OTEL_ENABLED": "true", "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"})
    def test_otel_enabled(self):
        """OTel initializes when OTEL_ENABLED=true."""
        import importlib
        import insights_kafka_service.telemetry as telemetry_mod

        importlib.reload(telemetry_mod)
        telemetry_mod._otel_initialized = False
        telemetry_mod.init_otel()
        assert telemetry_mod._otel_initialized is True

        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        assert provider is not None

    @patch.dict(os.environ, {"OTEL_ENABLED": "true", "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"})
    def test_otel_idempotent(self):
        """Calling init_otel() multiple times is a no-op after first init."""
        import importlib
        import insights_kafka_service.telemetry as telemetry_mod

        importlib.reload(telemetry_mod)
        telemetry_mod._otel_initialized = False
        telemetry_mod.init_otel()
        telemetry_mod.init_otel()
        assert telemetry_mod._otel_initialized is True

    @patch.dict(os.environ, {"OTEL_ENABLED": "true", "IMAGE_TAG": "abc123", "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"})
    def test_service_version_from_image_tag(self):
        """service.version resource attribute is set from IMAGE_TAG env var."""
        import importlib
        import insights_kafka_service.telemetry as telemetry_mod

        importlib.reload(telemetry_mod)
        telemetry_mod._otel_initialized = False
        telemetry_mod.init_otel()

        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider

        provider = trace.get_tracer_provider()
        assert isinstance(provider, TracerProvider)
        resource_attrs = dict(provider.resource.attributes)
        assert resource_attrs["service.version"] == "abc123"
        assert resource_attrs["service.name"] == "insights-engine"

    @patch.dict(os.environ, {"OTEL_ENABLED": "true", "OTEL_TRACES_EXPORTER": "none"})
    def test_traces_exporter_none(self):
        """No exporter span processor is added when OTEL_TRACES_EXPORTER=none."""
        import importlib
        import insights_kafka_service.telemetry as telemetry_mod

        importlib.reload(telemetry_mod)
        telemetry_mod._otel_initialized = False
        telemetry_mod.init_otel()
        assert telemetry_mod._otel_initialized is True

        from opentelemetry import trace
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = trace.get_tracer_provider()
        bsp_processors = [
            sp for sp in provider._active_span_processor._span_processors
            if isinstance(sp, BatchSpanProcessor)
        ]
        assert len(bsp_processors) == 0


class TestSamplingRate:
    """Tests for sampling rate parsing."""

    @patch.dict(os.environ, {"OTEL_SAMPLING_RATE": "0.5"})
    def test_valid_rate(self):
        import importlib
        import insights_kafka_service.telemetry as telemetry_mod

        importlib.reload(telemetry_mod)
        rate = telemetry_mod._parse_sampling_rate()
        assert rate == 0.5

    @patch.dict(os.environ, {"OTEL_SAMPLING_RATE": "invalid"})
    def test_invalid_rate_falls_back(self):
        import importlib
        import insights_kafka_service.telemetry as telemetry_mod

        importlib.reload(telemetry_mod)
        rate = telemetry_mod._parse_sampling_rate()
        assert rate == 1.0

    @patch.dict(os.environ, {"OTEL_SAMPLING_RATE": "2.0"})
    def test_rate_clamped_to_max(self):
        import importlib
        import insights_kafka_service.telemetry as telemetry_mod

        importlib.reload(telemetry_mod)
        rate = telemetry_mod._parse_sampling_rate()
        assert rate == 1.0

    @patch.dict(os.environ, {"OTEL_SAMPLING_RATE": "-0.5"})
    def test_rate_clamped_to_min(self):
        import importlib
        import insights_kafka_service.telemetry as telemetry_mod

        importlib.reload(telemetry_mod)
        rate = telemetry_mod._parse_sampling_rate()
        assert rate == 0.0


class TestContextPropagation:
    """Tests for trace context extraction and injection."""

    def test_extract_context_with_valid_traceparent(self):
        traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        headers = [("traceparent", traceparent.encode("utf-8"))]

        with patch.dict(os.environ, {"OTEL_ENABLED": "true"}):
            import importlib
            import insights_kafka_service.telemetry as telemetry_mod

            importlib.reload(telemetry_mod)
            ctx = telemetry_mod.extract_context_from_headers(headers)
            assert ctx is not None

    def test_extract_context_with_no_headers(self):
        from insights_kafka_service.telemetry import extract_context_from_headers

        ctx = extract_context_from_headers(None)
        assert ctx is None

    def test_extract_context_with_empty_headers(self):
        from insights_kafka_service.telemetry import extract_context_from_headers

        ctx = extract_context_from_headers([])
        assert ctx is None

    @patch.dict(os.environ, {"OTEL_ENABLED": "true", "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"})
    def test_inject_context_into_headers(self):
        """inject_context_into_headers produces traceparent when span is active."""
        import importlib
        import insights_kafka_service.telemetry as telemetry_mod

        importlib.reload(telemetry_mod)
        telemetry_mod._otel_initialized = False
        telemetry_mod.init_otel()

        tracer = telemetry_mod.get_tracer("test")
        with tracer.start_as_current_span("test-span"):
            headers = telemetry_mod.inject_context_into_headers()
            header_keys = [k for k, _ in headers]
            assert "traceparent" in header_keys

    @patch.dict(os.environ, {"OTEL_ENABLED": "false"})
    def test_inject_context_disabled(self):
        """inject_context_into_headers returns empty when OTel disabled."""
        import importlib
        import insights_kafka_service.telemetry as telemetry_mod

        importlib.reload(telemetry_mod)
        headers = telemetry_mod.inject_context_into_headers()
        assert headers == []


class TestLogCorrelation:
    """Tests for OTel trace_id/span_id injection into log records."""

    def test_filter_adds_null_without_active_span(self):
        from insights_kafka_service.log_configurator import ContextualFilter

        f = ContextualFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        result = f.filter(record)
        assert result is True
        assert record.trace_id is None
        assert record.span_id is None

    @patch.dict(os.environ, {"OTEL_ENABLED": "true", "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"})
    def test_filter_adds_trace_ids_with_active_span(self):
        import importlib
        import insights_kafka_service.telemetry as telemetry_mod

        importlib.reload(telemetry_mod)
        telemetry_mod._otel_initialized = False
        telemetry_mod.init_otel()

        from insights_kafka_service.log_configurator import ContextualFilter

        f = ContextualFilter()
        tracer = telemetry_mod.get_tracer("test")

        with tracer.start_as_current_span("log-test"):
            record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
            f.filter(record)
            assert record.trace_id is not None
            assert len(record.trace_id) == 32
            assert record.span_id is not None
            assert len(record.span_id) == 16


class TestRHAttributeSpanProcessor:
    """Tests for the custom SpanProcessor that sets rh.* attributes."""

    @patch.dict(os.environ, {"OTEL_ENABLED": "true", "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"})
    def test_rh_service_set_on_spans(self):
        import importlib
        import insights_kafka_service.telemetry as telemetry_mod

        importlib.reload(telemetry_mod)
        telemetry_mod._otel_initialized = False
        telemetry_mod.init_otel()

        from opentelemetry import trace
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        exporter = InMemorySpanExporter()
        provider = trace.get_tracer_provider()

        provider.add_span_processor(SimpleSpanProcessor(exporter))

        tracer = trace.get_tracer("test")
        with tracer.start_as_current_span("test-span"):
            pass

        spans = exporter.get_finished_spans()
        assert len(spans) >= 1
        span = spans[0]
        assert span.attributes.get("rh.service") == "insights-engine"

    @patch.dict(os.environ, {"OTEL_ENABLED": "true", "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"})
    def test_rh_org_id_propagated_from_threadctx(self):
        import importlib
        import insights_kafka_service.telemetry as telemetry_mod

        importlib.reload(telemetry_mod)
        telemetry_mod._otel_initialized = False
        telemetry_mod.init_otel()

        from opentelemetry import trace
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        exporter = InMemorySpanExporter()
        provider = trace.get_tracer_provider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))

        telemetry_mod.threadctx.org_id = "12345"
        telemetry_mod.threadctx.request_id = "req-abc"

        tracer = trace.get_tracer("test")
        with tracer.start_as_current_span("test-span"):
            pass

        spans = exporter.get_finished_spans()
        assert len(spans) >= 1
        span = spans[0]
        assert span.attributes.get("rh.org_id") == "12345"
        assert span.attributes.get("rh.request_id") == "req-abc"


class TestInstrumentOutboundHttp:
    """Tests for outbound HTTP instrumentation."""

    @patch.dict(os.environ, {"OTEL_ENABLED": "false"})
    def test_noop_when_disabled(self):
        import importlib
        import insights_kafka_service.telemetry as telemetry_mod

        importlib.reload(telemetry_mod)
        telemetry_mod.instrument_outbound_http()

    @patch.dict(os.environ, {"OTEL_ENABLED": "true", "OTEL_HTTP_OUTBOUND_ENABLED": "false"})
    def test_noop_when_http_disabled(self):
        import importlib
        import insights_kafka_service.telemetry as telemetry_mod

        importlib.reload(telemetry_mod)
        telemetry_mod.instrument_outbound_http()
