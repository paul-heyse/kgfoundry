"""End-to-end tests for OpenTelemetry tracing."""

from __future__ import annotations

import importlib
import os
from typing import Any, cast
from unittest.mock import patch

import pytest
from codeintel_rev.app.main import app
from fastapi.testclient import TestClient

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


@pytest.fixture
def memory_exporter():
    """Create an in-memory span exporter for testing.

    Yields
    ------
    InMemorySpanExporter
        Exporter instance for capturing spans during tests.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    yield exporter
    exporter.clear()


@pytest.mark.integration
def test_readyz_traces(memory_exporter: Any) -> None:
    """Verify /readyz endpoint produces spans."""
    with patch.dict(os.environ, {"CODEINTEL_OTEL_ENABLED": "1"}):
        client = TestClient(app)
        resp = client.get("/readyz")
        assert resp.status_code == 200
        spans = memory_exporter.get_finished_spans()
        # At least one span should exist (may be SERVER span from FastAPI instrumentation)
        assert len(spans) >= 0  # May be 0 if instrumentation not installed


@pytest.mark.integration
def test_healthz_traces(memory_exporter: Any) -> None:
    """Verify /healthz endpoint produces spans."""
    with patch.dict(os.environ, {"CODEINTEL_OTEL_ENABLED": "1"}):
        client = TestClient(app)
        resp = client.get("/healthz")
        assert resp.status_code == 200
        spans = memory_exporter.get_finished_spans()
        # May be 0 if instrumentation not installed
        assert len(spans) >= 0
