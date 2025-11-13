"""OpenTelemetry logging bootstrap helpers."""

from __future__ import annotations

import importlib
import logging
import os
from collections.abc import Iterable

from kgfoundry_common.logging import get_logger

try:  # pragma: no cover - optional dependency
    from opentelemetry._logs import set_logger_provider
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.resources import Resource
except ImportError:  # pragma: no cover - instrumentation optional
    set_logger_provider = None  # type: ignore[assignment]
    LoggerProvider = None  # type: ignore[assignment]
    LoggingHandler = None  # type: ignore[assignment]
    BatchLogRecordProcessor = None  # type: ignore[assignment]
    Resource = None  # type: ignore[assignment]

try:  # pragma: no cover - exporter optional
    from opentelemetry.exporter.otlp.proto.http.log_exporter import (  # type: ignore[reportMissingImports]
        OTLPLogExporter,
    )
except ImportError:  # pragma: no cover - exporter missing
    OTLPLogExporter = None  # type: ignore[assignment]


LOGGER = get_logger(__name__)
_INIT_STATE = {"done": False}

__all__ = ["init_otel_logging"]


def _should_enable() -> bool:
    raw = os.getenv("CODEINTEL_LOGS_ENABLED")
    if raw is None:
        raw = os.getenv("CODEINTEL_TELEMETRY")
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _instrument_stdlib_logging() -> None:
    """Enable OpenTelemetry's stdlib logging bridge when the package is installed."""
    try:
        logging_module = importlib.import_module("opentelemetry.instrumentation.logging")
    except ImportError:  # pragma: no cover - optional instrumentation
        LOGGER.debug("OpenTelemetry logging instrumentor unavailable")
        return

    instrumentor_cls = getattr(logging_module, "LoggingInstrumentor", None)
    if instrumentor_cls is None:  # pragma: no cover - defensive
        LOGGER.debug("OpenTelemetry logging instrumentor missing LoggingInstrumentor")
        return

    try:
        instrumentor_cls().instrument(set_logging_format=True)
    except (RuntimeError, ValueError):  # pragma: no cover - defensive
        LOGGER.debug("Failed to instrument logging", exc_info=True)


def init_otel_logging(
    *,
    service_name: str = "codeintel-mcp",
    exporters: Iterable[str] = ("otlp",),
    otlp_endpoint: str | None = None,
    level: int = logging.INFO,
) -> None:
    """Bridge stdlib logging into OpenTelemetry logs when available."""
    if _INIT_STATE["done"] or not _should_enable():
        return
    if (
        set_logger_provider is None or LoggerProvider is None or Resource is None
    ):  # pragma: no cover
        LOGGER.debug("OpenTelemetry logging components unavailable; skipping init")
        return

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.namespace": "kgfoundry",
            "codeintel.role": "mcp",
        }
    )
    provider = LoggerProvider(resource=resource)
    set_logger_provider(provider)

    if "otlp" in exporters and OTLPLogExporter is not None and BatchLogRecordProcessor is not None:
        endpoint = otlp_endpoint or os.getenv(
            "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"
        )
        try:
            exporter = OTLPLogExporter(endpoint=f"{endpoint.rstrip('/')}/v1/logs")
        except (OSError, ValueError, RuntimeError):  # pragma: no cover - exporter misconfigured
            LOGGER.warning("Failed to initialise OTLP log exporter", exc_info=True)
        else:
            processor = BatchLogRecordProcessor(exporter)
            provider.add_log_record_processor(processor)

    if LoggingHandler is None:  # pragma: no cover - guard
        LOGGER.debug("OpenTelemetry logging handler unavailable")
        return

    handler = LoggingHandler(level=level, logger_provider=provider)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(min(root_logger.level or level, level))

    _instrument_stdlib_logging()
    _INIT_STATE["done"] = True
