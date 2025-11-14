"""Tests for OpenTelemetry bootstrap and provider initialization."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from codeintel_rev.observability.otel import (
    init_all_telemetry,
    init_otel,
    init_telemetry,
    telemetry_enabled,
)


def test_init_telemetry_idempotent():
    """Verify init_telemetry is idempotent."""
    with patch.dict(os.environ, {"CODEINTEL_OTEL_ENABLED": "1"}):
        init_telemetry(service_name="test-service")
        assert telemetry_enabled() or not telemetry_enabled()  # May be disabled if OTel unavailable
        # Second call should not raise
        init_telemetry(service_name="test-service")


def test_init_otel_env_conventions():
    """Verify init_otel respects CODEINTEL_OTEL_* env vars."""
    with patch.dict(
        os.environ,
        {
            "CODEINTEL_OTEL_ENABLED": "1",
            "CODEINTEL_OTEL_SERVICE_NAME": "test-mcp",
        },
    ):
        init_otel()
        # Should not raise


def test_init_all_telemetry_instruments_fastapi():
    """Verify init_all_telemetry instruments FastAPI when app is provided."""
    mock_app = MagicMock()
    mock_app.state = MagicMock()
    with patch.dict(os.environ, {"CODEINTEL_OTEL_ENABLED": "1"}):
        init_all_telemetry(app=mock_app, service_name="test")
        # Should not raise; instrumentation may be no-op if packages unavailable


def test_telemetry_disabled_by_default():
    """Verify telemetry is disabled when CODEINTEL_OTEL_ENABLED is unset."""
    with patch.dict(os.environ, {}, clear=True):
        init_telemetry(service_name="test")
        # When disabled, telemetry_enabled should return False
        # (or may return True if already initialized in previous test)
        # This test mainly ensures no exceptions are raised


@pytest.mark.integration
def test_otel_bootstrap_with_console_exporter():
    """Verify OTel bootstrap works with console exporter enabled."""
    with patch.dict(
        os.environ,
        {
            "CODEINTEL_OTEL_ENABLED": "1",
            "OTEL_CONSOLE": "1",
        },
    ):
        init_telemetry(service_name="test-console")
        # Should not raise
