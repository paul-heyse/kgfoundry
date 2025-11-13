"""Structured logging bridge + optional OTLP exporter."""

from __future__ import annotations

import logging
import os

from codeintel_rev.telemetry.otel import _env_flag, build_resource
from kgfoundry_common.logging import setup_logging

try:  # pragma: no cover - optional dependency
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
except ImportError:  # pragma: no cover - fallback
    OTLPLogExporter = None
    LoggerProvider = None
    LoggingHandler = None
    BatchLogRecordProcessor = None

LOGGER = logging.getLogger(__name__)
_LOGGING_INSTALLED = False


def install_structured_logging(level: int = logging.INFO) -> None:
    """Install JSON logging and optional OTLP log export."""
    global _LOGGING_INSTALLED  # noqa: PLW0603
    if _LOGGING_INSTALLED:
        return
    setup_logging(level=level)
    _LOGGING_INSTALLED = True
    if not _env_flag("TELEMETRY_ENABLED", default=True):
        return
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return
    if any(
        component is None
        for component in (OTLPLogExporter, LoggerProvider, LoggingHandler, BatchLogRecordProcessor)
    ):
        LOGGER.warning("OpenTelemetry log exporter unavailable; skipping structured bridge")
        return

    provider = LoggerProvider(
        resource=build_resource(
            service_name=os.getenv("OTEL_SERVICE_NAME", "codeintel-mcp"),
            service_version=os.getenv("OTEL_SERVICE_VERSION"),
        )
    )
    exporter = OTLPLogExporter(
        endpoint=endpoint, insecure=_env_flag("OTEL_EXPORTER_OTLP_INSECURE", default=True)
    )
    provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    handler = LoggingHandler(level=level, logger_provider=provider)
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(level)
