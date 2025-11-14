"""Tests for log-trace correlation (trace_id/span_id in log records)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from opentelemetry.sdk.trace.export import (
        InMemorySpanExporter,  # type: ignore[reportAttributeAccessIssue]
        SimpleSpanProcessor,  # type: ignore[reportAttributeAccessIssue]
    )

try:
    from codeintel_rev.observability.otel import current_span_id, current_trace_id
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        InMemorySpanExporter,  # type: ignore[reportAttributeAccessIssue]
        SimpleSpanProcessor,  # type: ignore[reportAttributeAccessIssue]
    )

    _OTELEMETRY_AVAILABLE = True
except ImportError:
    _OTELEMETRY_AVAILABLE = False
    # Stub types for runtime when OTel is unavailable (tests will be skipped)
    InMemorySpanExporter = object  # type: ignore[assignment,misc]
    SimpleSpanProcessor = object  # type: ignore[assignment,misc]

OTELEMETRY_AVAILABLE = _OTELEMETRY_AVAILABLE


@pytest.mark.skipif(not OTELEMETRY_AVAILABLE, reason="OpenTelemetry packages not available")
def test_trace_id_in_span_context():  # type: ignore[misc]
    """Verify trace_id is available in span context."""
    if not OTELEMETRY_AVAILABLE:
        pytest.skip("OpenTelemetry packages not available")
    exporter = InMemorySpanExporter()  # type: ignore[misc]
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))  # type: ignore[misc]
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("test_span"):
        trace_id = current_trace_id()
        assert trace_id is not None
        assert len(trace_id) == 32  # Hex trace ID is 32 chars


@pytest.mark.skipif(not OTELEMETRY_AVAILABLE, reason="OpenTelemetry packages not available")
def test_span_id_in_span_context():  # type: ignore[misc]
    """Verify span_id is available in span context."""
    if not OTELEMETRY_AVAILABLE:
        pytest.skip("OpenTelemetry packages not available")
    exporter = InMemorySpanExporter()  # type: ignore[misc]
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))  # type: ignore[misc]
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("test_span"):
        span_id = current_span_id()
        assert span_id is not None
        assert len(span_id) == 16  # Hex span ID is 16 chars


@pytest.mark.skipif(not OTELEMETRY_AVAILABLE, reason="OpenTelemetry packages not available")
def test_log_record_contains_trace_context():  # type: ignore[misc]
    """Verify log records can access trace context."""
    if not OTELEMETRY_AVAILABLE:
        pytest.skip("OpenTelemetry packages not available")
    exporter = InMemorySpanExporter()  # type: ignore[misc]
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))  # type: ignore[misc]
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
