"""Structured logging bridge + optional OTLP exporter."""

from __future__ import annotations

import logging

from codeintel_rev.observability.logs import init_otel_logging
from kgfoundry_common.logging import setup_logging

LOGGER = logging.getLogger(__name__)
_LOGGING_STATE: dict[str, bool] = {"installed": False}


def install_structured_logging(level: int = logging.INFO) -> None:
    """Install JSON logging and delegate OpenTelemetry export to observability stack."""
    if _LOGGING_STATE["installed"]:
        return
    setup_logging(level=level)
    _LOGGING_STATE["installed"] = True
    try:
        init_otel_logging(level=level)
    except Exception:  # pragma: no cover - defensive
        LOGGER.debug("Failed to initialize OpenTelemetry logging bridge", exc_info=True)
