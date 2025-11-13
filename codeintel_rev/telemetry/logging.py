"""Structured logging bridge + optional OTLP exporter."""

from __future__ import annotations

import importlib
import logging
import os
from typing import Any

from codeintel_rev.telemetry.otel import _env_flag, build_resource
from kgfoundry_common.logging import setup_logging

LOGGER = logging.getLogger(__name__)
_LOGGING_STATE: dict[str, bool] = {"installed": False}


def _load_logging_dependencies() -> dict[str, Any] | None:
    """Import OpenTelemetry logging modules lazily to keep deps optional.

    Returns
    -------
    dict[str, Any] | None
        Mapping of logging helpers when available; ``None`` if OTLP log
        dependencies are missing.
    """
    try:
        exporter_mod = importlib.import_module(
            "opentelemetry.exporter.otlp.proto.http._log_exporter"
        )
        logs_mod = importlib.import_module("opentelemetry.sdk._logs")
        logs_export_mod = importlib.import_module("opentelemetry.sdk._logs.export")
    except ImportError:  # pragma: no cover - optional dependency
        return None
    exporter_cls = getattr(exporter_mod, "OTLPLogExporter", None)
    provider_cls = getattr(logs_mod, "LoggerProvider", None)
    handler_cls = getattr(logs_mod, "LoggingHandler", None)
    processor_cls = getattr(logs_export_mod, "BatchLogRecordProcessor", None)
    if any(
        component is None for component in (exporter_cls, provider_cls, handler_cls, processor_cls)
    ):
        return None
    return {
        "exporter_cls": exporter_cls,
        "provider_cls": provider_cls,
        "handler_cls": handler_cls,
        "processor_cls": processor_cls,
    }


def install_structured_logging(level: int = logging.INFO) -> None:
    """Install JSON logging and optional OTLP log export."""
    if _LOGGING_STATE["installed"]:
        return
    setup_logging(level=level)
    _LOGGING_STATE["installed"] = True
    if not _env_flag("TELEMETRY_ENABLED", default=True):
        return
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return
    deps = _load_logging_dependencies()
    if deps is None:
        LOGGER.warning("OpenTelemetry log exporter unavailable; skipping structured bridge")
        return
    exporter_cls = deps["exporter_cls"]
    provider_cls = deps["provider_cls"]
    handler_cls = deps["handler_cls"]
    processor_cls = deps["processor_cls"]

    provider = provider_cls(
        resource=build_resource(
            service_name=os.getenv("OTEL_SERVICE_NAME", "codeintel-mcp"),
            service_version=os.getenv("OTEL_SERVICE_VERSION"),
        )
    )
    exporter = exporter_cls(
        endpoint=endpoint,
        insecure=_env_flag("OTEL_EXPORTER_OTLP_INSECURE", default=True),
    )
    provider.add_log_record_processor(processor_cls(exporter))
    handler = handler_cls(level=level, logger_provider=provider)
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(level)
