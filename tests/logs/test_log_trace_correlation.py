"""Tests for log-trace correlation (trace_id/span_id in log records)."""

from __future__ import annotations

import importlib
import logging
from typing import Any, cast

import pytest
from codeintel_rev.observability.otel import current_span_id, current_trace_id

try:
    trace_module = importlib.import_module("opentelemetry.trace")
    sdk_trace_module = importlib.import_module("opentelemetry.sdk.trace")
    exporter_module = importlib.import_module("opentelemetry.sdk.trace.export")
except ImportError:
    pytest.skip("OpenTelemetry packages not available", allow_module_level=True)

trace = cast("Any", trace_module)
TracerProvider = cast("type[Any]", sdk_trace_module.TracerProvider)
InMemorySpanExporter = cast("type[Any]", exporter_module.InMemorySpanExporter)
SimpleSpanProcessor = cast("type[Any]", exporter_module.SimpleSpanProcessor)


def test_trace_id_in_span_context() -> None:
    """Verify trace_id is available in span context."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("test_span"):
        trace_id = current_trace_id()
        assert trace_id is not None
        assert len(trace_id) == 32  # Hex trace ID is 32 chars


def test_span_id_in_span_context() -> None:
    """Verify span_id is available in span context."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("test_span"):
        span_id = current_span_id()
        assert span_id is not None
        assert len(span_id) == 16  # Hex span ID is 16 chars


def test_log_record_contains_trace_context() -> None:
    """Verify log records can access trace context."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    logger = logging.getLogger(__name__)
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("test_log_span"):
        trace_id = current_trace_id()
        span_id = current_span_id()
        # Log a message and verify context is available
        logger.info("test message", extra={"trace_id": trace_id, "span_id": span_id})
        assert trace_id is not None
        assert span_id is not None
