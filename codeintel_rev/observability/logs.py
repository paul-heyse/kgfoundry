"""OpenTelemetry logging bootstrap helpers."""

from __future__ import annotations

import importlib
import logging
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)
_INIT_STATE = {"done": False}

__all__ = ["init_otel_logging"]


@dataclass(slots=True)
class _LoggingAPI:
    set_logger_provider: Callable[[Any], None]
    logger_provider_cls: type[Any]
    handler_cls: type[Any]
    processor_cls: type[Any] | None
    resource_cls: type[Any]
    exporter_cls: type[Any] | None


@lru_cache(maxsize=1)
def _load_logging_api() -> _LoggingAPI | None:
    """Return Otel logging classes when the dependency is installed.

    Returns
    -------
    _LoggingAPI | None
        Structured set of constructors and factories required for log export,
        or ``None`` when OpenTelemetry logging modules are unavailable.
    """
    try:
        logs_module = importlib.import_module("opentelemetry._logs")
        sdk_logs_module = importlib.import_module("opentelemetry.sdk._logs")
        export_module = importlib.import_module("opentelemetry.sdk._logs.export")
        resource_module = importlib.import_module("opentelemetry.sdk.resources")
    except ImportError:
        return None
    exporter_cls = None
    try:
        exporter_module = importlib.import_module(
            "opentelemetry.exporter.otlp.proto.http.log_exporter"
        )
        exporter_cls = exporter_module.OTLPLogExporter
    except (ImportError, AttributeError):
        exporter_cls = None
    try:
        processor_cls = export_module.BatchLogRecordProcessor
    except AttributeError:
        processor_cls = None
    return _LoggingAPI(
        set_logger_provider=logs_module.set_logger_provider,
        logger_provider_cls=sdk_logs_module.LoggerProvider,
        handler_cls=sdk_logs_module.LoggingHandler,
        processor_cls=processor_cls,
        resource_cls=resource_module.Resource,
        exporter_cls=exporter_cls,
    )


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
    api = _load_logging_api()
    if api is None:  # pragma: no cover
        LOGGER.debug("OpenTelemetry logging components unavailable; skipping init")
        return

    resource = api.resource_cls.create(
        {
            "service.name": service_name,
            "service.namespace": "kgfoundry",
            "codeintel.role": "mcp",
        }
    )
    provider = api.logger_provider_cls(resource=resource)
    api.set_logger_provider(provider)

    if (
        "otlp" in exporters
        and api.exporter_cls is not None
        and api.processor_cls is not None
    ):
        endpoint = otlp_endpoint or os.getenv(
            "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"
        )
        try:
            exporter = api.exporter_cls(endpoint=f"{endpoint.rstrip('/')}/v1/logs")
        except (OSError, ValueError, RuntimeError):  # pragma: no cover - exporter misconfigured
            LOGGER.warning("Failed to initialise OTLP log exporter", exc_info=True)
        else:
            processor = api.processor_cls(exporter)
            provider.add_log_record_processor(processor)

    if api.handler_cls is None:  # pragma: no cover - guard
        LOGGER.debug("OpenTelemetry logging handler unavailable")
        return

    handler = api.handler_cls(level=level, logger_provider=provider)
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(min(root_logger.level or level, level))

    _instrument_stdlib_logging()
    _INIT_STATE["done"] = True
