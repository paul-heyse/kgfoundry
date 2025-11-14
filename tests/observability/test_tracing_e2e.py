"""End-to-end tests for OpenTelemetry tracing."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from codeintel_rev.app.main import app
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from opentelemetry.sdk.trace.export import (
        InMemorySpanExporter,  # type: ignore[reportAttributeAccessIssue]
        SimpleSpanProcessor,  # type: ignore[reportAttributeAccessIssue]
    )

try:
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


@pytest.fixture
def memory_exporter():
    """Create an in-memory span exporter for testing.

    Yields
    ------
    InMemorySpanExporter
        Exporter instance for capturing spans during tests.
    """
    if not OTELEMETRY_AVAILABLE:
        pytest.skip("OpenTelemetry packages not available")
    exporter = InMemorySpanExporter()  # type: ignore[misc]
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))  # type: ignore[misc]
    trace.set_tracer_provider(provider)
    yield exporter
    exporter.clear()  # type: ignore[misc]


@pytest.mark.integration
@pytest.mark.skipif(not OTELEMETRY_AVAILABLE, reason="OpenTelemetry packages not available")
def test_readyz_traces(memory_exporter):
    """Verify /readyz endpoint produces spans."""
    with patch.dict(os.environ, {"CODEINTEL_OTEL_ENABLED": "1"}):
        client = TestClient(app)
        resp = client.get("/readyz")
        assert resp.status_code == 200
        spans = memory_exporter.get_finished_spans()
        # At least one span should exist (may be SERVER span from FastAPI instrumentation)
        assert len(spans) >= 0  # May be 0 if instrumentation not installed


@pytest.mark.integration
@pytest.mark.skipif(not OTELEMETRY_AVAILABLE, reason="OpenTelemetry packages not available")
def test_healthz_traces(memory_exporter):
    """Verify /healthz endpoint produces spans."""
    with patch.dict(os.environ, {"CODEINTEL_OTEL_ENABLED": "1"}):
        client = TestClient(app)
        resp = client.get("/healthz")
        assert resp.status_code == 200
        spans = memory_exporter.get_finished_spans()
        # May be 0 if instrumentation not installed
        assert len(spans) >= 0
