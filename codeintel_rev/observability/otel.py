"""Optional OpenTelemetry bootstrap helpers."""

from __future__ import annotations

import importlib
import os
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Protocol

from kgfoundry_common.logging import get_logger
from kgfoundry_common.observability import start_span

LOGGER = get_logger(__name__)

SpanAttribute = str | int | float | bool


class _TelemetryState:
    """Mutable telemetry state shared across module functions."""

    __slots__ = ("initialized", "trace_module", "tracing_enabled")

    def __init__(self) -> None:
        self.initialized = False
        self.tracing_enabled = False
        self.trace_module: ModuleType | None = None


class SupportsState(Protocol):
    """Protocol describing FastAPI-style objects exposing ``state``."""

    state: Any


@dataclass(slots=True, frozen=True)
class _TraceHandles:
    trace: ModuleType
    sdk_trace: ModuleType
    exporter: ModuleType
    resource: ModuleType
    otlp_http: ModuleType | None


_STATE = _TelemetryState()
_SPAN_STR_MAX = int(os.getenv("CODEINTEL_TELEMETRY_MAX_FIELD", "256"))


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _sanitize_span_attrs(attrs: Mapping[str, object] | None) -> dict[str, SpanAttribute]:
    if not attrs:
        return {}
    sanitized: dict[str, SpanAttribute] = {}
    for key, value in attrs.items():
        sanitized[str(key)] = _coerce_span_value(value)
    return sanitized


def _coerce_span_value(value: object) -> SpanAttribute:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= _SPAN_STR_MAX:
            return value
        return f"{value[:_SPAN_STR_MAX]}…"
    if value is None:
        return "null"
    return str(value)


def _should_enable() -> bool:
    return _env_flag("CODEINTEL_TELEMETRY", default=False)


def _load_trace_modules() -> _TraceHandles | None:
    try:
        trace_module = importlib.import_module("opentelemetry.trace")
        sdk_trace = importlib.import_module("opentelemetry.sdk.trace")
        exporter_mod = importlib.import_module("opentelemetry.sdk.trace.export")
        resource_mod = importlib.import_module("opentelemetry.sdk.resources")
    except ImportError as exc:  # pragma: no cover - optional dependency
        LOGGER.warning("OpenTelemetry packages unavailable; telemetry disabled", exc_info=exc)
        return None
    try:
        otlp_mod = importlib.import_module("opentelemetry.exporter.otlp.proto.http.trace_exporter")
    except ImportError:
        otlp_mod = None
    return _TraceHandles(
        trace=trace_module,
        sdk_trace=sdk_trace,
        exporter=exporter_mod,
        resource=resource_mod,
        otlp_http=otlp_mod,
    )


def _build_provider(
    handles: _TraceHandles,
    service_name: str,
    endpoint: str | None,
) -> None:
    resource = handles.resource.Resource.create({"service.name": service_name})
    provider = handles.sdk_trace.TracerProvider(resource=resource)
    processors = 0
    if endpoint and handles.otlp_http is not None:
        exporter = handles.otlp_http.OTLPSpanExporter(endpoint=endpoint)
        provider.add_span_processor(handles.exporter.BatchSpanProcessor(exporter))
        processors += 1
    elif endpoint and handles.otlp_http is None:
        LOGGER.warning("OTLP exporter requested but opentelemetry exporter package is missing")
    if _env_flag("OTEL_CONSOLE", default=False):
        provider.add_span_processor(
            handles.exporter.SimpleSpanProcessor(handles.exporter.ConsoleSpanExporter())
        )
        processors += 1
    if processors == 0:
        LOGGER.info(
            "OpenTelemetry enabled without exporters; spans will remain in-process only.",
        )
    handles.trace.set_tracer_provider(provider)


def telemetry_enabled() -> bool:
    """Return ``True`` when tracing has been configured for this process.

    Returns
    -------
    bool
        ``True`` if telemetry successfully bootstrapped, otherwise ``False``.
    """
    return _STATE.tracing_enabled


def init_telemetry(
    app: SupportsState | None = None,
    *,
    service_name: str = "codeintel_rev",
    otlp_endpoint: str | None = None,
) -> None:
    """Best-effort OpenTelemetry bootstrap (safe no-op when disabled/unavailable).

    Parameters
    ----------
    app : SupportsState | None, optional
        FastAPI application instance for storing telemetry state.
    service_name : str, optional
        Resource attribute for exported spans. Defaults to ``codeintel_rev``.
    otlp_endpoint : str | None, optional
        Override for OTLP HTTP endpoint. When ``None``, uses
        ``OTEL_EXPORTER_OTLP_ENDPOINT``.
    """
    if _STATE.initialized:
        if app is not None:
            app.state.telemetry_enabled = _STATE.tracing_enabled
        return

    if not _should_enable():
        _STATE.initialized = True
        _STATE.tracing_enabled = False
        if app is not None:
            app.state.telemetry_enabled = False
        return

    handles = _load_trace_modules()
    if handles is None:
        _STATE.initialized = True
        _STATE.tracing_enabled = False
        if app is not None:
            app.state.telemetry_enabled = False
        return

    endpoint = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    _build_provider(handles, service_name, endpoint)
    _STATE.trace_module = handles.trace
    _STATE.tracing_enabled = True
    _STATE.initialized = True
    if app is not None:
        app.state.telemetry_enabled = True


def as_span(name: str, **attrs: object) -> AbstractContextManager[None]:
    """Create a span context that no-ops when telemetry is disabled.

    Extended Summary
    ----------------
    Returns a context manager that creates an OpenTelemetry span when tracing
    is enabled, or a no-op context manager when disabled. Attributes are
    sanitized (coerced to span-compatible types, truncated if needed) before
    being attached to the span.

    Parameters
    ----------
    name : str
        Span name used for identification in traces.
    **attrs : object
        Arbitrary keyword arguments converted to span attributes. Values are
        coerced to str/int/float/bool and truncated if strings exceed max length.

    Returns
    -------
    AbstractContextManager[None]
        Context manager that enters/exits a span when telemetry is enabled,
        or a no-op context manager when disabled. Always yields None.
    """
    span_attrs = _sanitize_span_attrs(attrs)
    return start_span(name, attributes=span_attrs or None)


def record_span_event(name: str, **attrs: object) -> None:
    """Attach ``name`` as an event on the current span when tracing is active."""
    if not _STATE.tracing_enabled or _STATE.trace_module is None:
        return
    span = getattr(_STATE.trace_module, "get_current_span", None)
    if span is None:
        return
    current = span()
    add_event = getattr(current, "add_event", None)
    is_recording = getattr(current, "is_recording", None)
    if add_event is None:
        return
    if callable(is_recording) and not is_recording():
        return
    span_attrs = _sanitize_span_attrs(attrs)
    try:
        if span_attrs:
            add_event(name, attributes=span_attrs)
        else:
            add_event(name)
    except (RuntimeError, ValueError, TypeError):  # pragma: no cover - defensive
        LOGGER.debug("Failed to record OpenTelemetry event; continuing", exc_info=True)


__all__ = ["as_span", "init_telemetry", "record_span_event", "telemetry_enabled"]
