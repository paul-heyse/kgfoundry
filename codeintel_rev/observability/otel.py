"""Optional OpenTelemetry bootstrap helpers."""

from __future__ import annotations

import importlib
import os
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager, suppress
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Protocol

from codeintel_rev.observability.logs import init_otel_logging
from kgfoundry_common.logging import get_logger
from kgfoundry_common.observability import start_span

try:  # pragma: no cover - optional dependency
    from prometheus_client import start_http_server as _prom_start_http_server
except ImportError:  # pragma: no cover - optional dependency
    _prom_start_http_server = None

try:  # pragma: no cover - optional dependency
    from codeintel_rev.observability.flight_recorder import (
        install_flight_recorder as _install_flight_recorder,
    )
except ImportError:  # pragma: no cover - optional dependency
    _install_flight_recorder = None

LOGGER = get_logger(__name__)

SpanAttribute = str | int | float | bool


class _TelemetryState:
    """Mutable telemetry state shared across module functions."""

    __slots__ = (
        "fastapi_instrumented",
        "httpx_instrumented",
        "initialized",
        "logging_instrumented",
        "metrics_initialized",
        "prometheus_running",
        "trace_module",
        "trace_provider",
        "tracing_enabled",
    )

    def __init__(self) -> None:
        self.initialized = False
        self.tracing_enabled = False
        self.trace_module: ModuleType | None = None
        self.trace_provider: object | None = None
        self.metrics_initialized = False
        self.fastapi_instrumented = False
        self.httpx_instrumented = False
        self.logging_instrumented = False
        self.prometheus_running = False


class SupportsState(Protocol):
    """Protocol describing FastAPI-style objects exposing ``state``."""

    state: Any


@dataclass(slots=True, frozen=True)
class _TraceHandles:
    trace: ModuleType
    sdk_trace: ModuleType
    exporter: ModuleType
    resource: ModuleType
    sampling: ModuleType | None
    otlp_http: ModuleType | None


_STATE = _TelemetryState()
_SPAN_STR_MAX = int(os.getenv("CODEINTEL_TELEMETRY_MAX_FIELD", "256"))
_RESOURCE_DETECTORS: Sequence[tuple[str, str]] = (
    ("opentelemetry_resourcedetector_process", "ProcessResourceDetector"),
    ("opentelemetry_resourcedetector_docker", "DockerResourceDetector"),
    ("opentelemetry_resourcedetector_kubernetes", "KubernetesResourceDetector"),
)


def _env_flag(name: str, *, default: bool = False) -> bool:
    """Check if an environment variable is set to a truthy value.

    This function reads an environment variable and returns True if it's set to
    a recognized truthy value ("1", "true", "yes", "on"), or returns the default
    value if the variable is unset or set to a falsy value.

    Parameters
    ----------
    name : str
        Environment variable name to check. The variable is read using os.getenv()
        and compared against truthy values (case-insensitive, whitespace-trimmed).
    default : bool, optional
        Default value to return when the environment variable is unset or not
        recognized as truthy (default: False). Used to provide fallback behavior
        when the flag is not explicitly configured.

    Returns
    -------
    bool
        True if the environment variable is set to a truthy value, otherwise
        returns the default value. Truthy values are "1", "true", "yes", "on"
        (case-insensitive, whitespace-trimmed).
    """
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
    if os.getenv("CODEINTEL_OTEL_ENABLED") is not None:
        return _env_flag("CODEINTEL_OTEL_ENABLED", default=False)
    return _env_flag("CODEINTEL_TELEMETRY", default=False)


def _optional_import(module_name: str) -> ModuleType | None:
    try:
        return importlib.import_module(module_name)
    except ImportError:  # pragma: no cover - optional dependency
        return None


def _load_trace_modules() -> _TraceHandles | None:
    try:
        trace_module = importlib.import_module("opentelemetry.trace")
        sdk_trace = importlib.import_module("opentelemetry.sdk.trace")
        exporter_mod = importlib.import_module("opentelemetry.sdk.trace.export")
        resource_mod = importlib.import_module("opentelemetry.sdk.resources")
        try:
            sampling_mod = importlib.import_module("opentelemetry.sdk.trace.sampling")
        except ImportError:
            sampling_mod = None
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
        sampling=sampling_mod,
        otlp_http=otlp_mod,
    )


def _parse_sampler_spec(raw: str) -> tuple[str, float | None]:
    spec = raw.strip().lower().replace("-", "_")
    ratio: float | None = None
    if ":" in spec:
        head, tail = spec.split(":", 1)
        spec = head
        try:
            ratio = float(tail)
        except ValueError:
            ratio = None
    return spec, ratio


def _build_sampler(handles: _TraceHandles, sampler_spec: str | None) -> object | None:
    if not sampler_spec or handles.sampling is None:
        return None
    spec, ratio = _parse_sampler_spec(sampler_spec)
    module = handles.sampling
    try:
        if spec in {"always_on", "alwayson"}:
            return module.ALWAYS_ON
        if spec in {"always_off", "alwaysoff"}:
            return module.ALWAYS_OFF
        if spec in {"traceidratio", "traceidratio_based"}:
            factory = getattr(module, "TraceIdRatioBased", None)
            if factory is None:
                return None
            return factory(max(0.0, min(1.0, ratio or 1.0)))
        if spec in {"parentbased_traceidratio", "parentbased"}:
            pb_factory = getattr(module, "ParentBased", None)
            ratio_factory = getattr(module, "TraceIdRatioBased", None)
            if pb_factory is None or ratio_factory is None:
                return None
            inner_ratio = max(0.0, min(1.0, ratio or 1.0))
            return pb_factory(ratio_factory(inner_ratio))
    except (AttributeError, TypeError, ValueError):  # pragma: no cover - defensive
        LOGGER.debug("Failed to instantiate sampler %s", sampler_spec, exc_info=True)
        return None
    LOGGER.warning("Unsupported sampler spec '%s'; falling back to default", sampler_spec)
    return None


def _build_resource(
    handles: _TraceHandles,
    service_name: str,
    service_version: str | None,
) -> object:
    try:
        semconv = importlib.import_module("opentelemetry.semconv.resource")
        attributes = getattr(semconv, "ResourceAttributes", None)
    except ImportError:  # pragma: no cover - optional dependency
        attributes = None
    service_name_key = (
        getattr(attributes, "SERVICE_NAME", "service.name")
        if attributes is not None
        else "service.name"
    )
    service_version_key = (
        getattr(attributes, "SERVICE_VERSION", "service.version")
        if attributes is not None
        else "service.version"
    )
    namespace_key = (
        getattr(attributes, "SERVICE_NAMESPACE", "service.namespace")
        if attributes is not None
        else "service.namespace"
    )
    resource_attrs: dict[str, object] = {
        service_name_key: service_name,
        namespace_key: os.getenv("CODEINTEL_OTEL_SERVICE_NAMESPACE", "kgfoundry"),
    }
    if service_version:
        resource_attrs[service_version_key] = service_version
    resource = handles.resource.Resource.create(resource_attrs)
    return _merge_detected_resources(resource)


def _merge_detected_resources(resource: object) -> object:
    """Augment ``resource`` with optional detector-provided attributes.

    Returns
    -------
    object
        Resource merged with detector-provided metadata.
    """
    merged = resource
    for module_name, detector_name in _RESOURCE_DETECTORS:
        module = _optional_import(module_name)
        if module is None:
            continue
        detector_cls = getattr(module, detector_name, None)
        if detector_cls is None:
            continue
        try:
            detector = detector_cls()
            detected = detector.detect()
        except (RuntimeError, ValueError, OSError):  # pragma: no cover - detector optional
            LOGGER.debug("Resource detector %s failed; continuing", detector_name, exc_info=True)
            continue
        if detected is None:
            continue
        merge_fn = getattr(merged, "merge", None)
        if callable(merge_fn):
            try:
                merged = merge_fn(detected)
            except (RuntimeError, ValueError, OSError):  # pragma: no cover - defensive
                LOGGER.debug("Failed to merge resource detector output", exc_info=True)
    return merged


def _build_provider(
    handles: _TraceHandles,
    resource: object,
    endpoint: str | None,
    sampler_spec: str | None,
) -> object:
    sampler = _build_sampler(handles, sampler_spec)
    provider = handles.sdk_trace.TracerProvider(resource=resource, sampler=sampler)
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
    return provider


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
    service_version: str | None = None,
    otlp_endpoint: str | None = None,
    enable_logging_instrumentation: bool = True,
    sampler: str | None = None,
    install_flight_recorder: bool = True,
) -> None:
    """Best-effort OpenTelemetry bootstrap (safe no-op when disabled/unavailable).

    Parameters
    ----------
    app : SupportsState | None, optional
        FastAPI application instance for storing telemetry state.
    service_name : str, optional
        Resource attribute for exported spans. Defaults to ``codeintel_rev``.
    service_version : str | None, optional
        Optional semantic version attached to the OpenTelemetry resource.
    otlp_endpoint : str | None, optional
        Override for OTLP HTTP endpoint. When ``None``, uses
        ``OTEL_EXPORTER_OTLP_ENDPOINT``.
    enable_logging_instrumentation : bool, optional
        When ``True`` attempts to enable OpenTelemetry logging instrumentation
        (safe no-op if instrumentation packages are unavailable).
    sampler : str | None, optional
        Optional sampler specification (e.g., ``parentbased_traceidratio:0.2``).
        When ``None`` defers to SDK defaults.
    install_flight_recorder : bool, optional
        When ``True`` installs the lightweight flight recorder span processor.
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
    sampler_spec = sampler or os.getenv("CODEINTEL_OTEL_SAMPLER")
    resource = _build_resource(handles, service_name, service_version)
    provider = _build_provider(handles, resource, endpoint, sampler_spec)
    _STATE.trace_module = handles.trace
    _STATE.trace_provider = provider
    _STATE.tracing_enabled = True
    _STATE.initialized = True
    if app is not None:
        app.state.telemetry_enabled = True
    if enable_logging_instrumentation:
        _install_logging_instrumentation()
    metrics_enabled = _env_flag("CODEINTEL_OTEL_METRICS_ENABLED", default=True)
    if metrics_enabled:
        metrics_endpoint = os.getenv("CODEINTEL_OTEL_METRICS_ENDPOINT", otlp_endpoint or None)
        _install_metrics_provider(resource, metrics_endpoint)
    if install_flight_recorder and _install_flight_recorder is not None:
        try:
            _install_flight_recorder(provider)
        except (RuntimeError, ValueError):  # pragma: no cover - defensive
            LOGGER.debug("Failed to install flight recorder", exc_info=True)


def init_otel(
    app: SupportsState | None = None,
    *,
    service_name: str | None = None,
    service_version: str | None = None,
    install_flight_recorder: bool = True,
) -> None:
    """Initialize tracing/metrics using the CODEINTEL_OTEL_* env conventions."""
    resolved_name = service_name or os.getenv("CODEINTEL_OTEL_SERVICE_NAME", "codeintel-mcp")
    endpoint = os.getenv("CODEINTEL_OTEL_EXPORTER_OTLP_ENDPOINT")
    sampler = os.getenv("CODEINTEL_OTEL_SAMPLER")
    enable_logs = _env_flag("CODEINTEL_OTEL_LOGS_ENABLED", default=True)
    init_telemetry(
        app=app,
        service_name=resolved_name,
        service_version=service_version,
        otlp_endpoint=endpoint,
        enable_logging_instrumentation=enable_logs,
        sampler=sampler,
        install_flight_recorder=install_flight_recorder,
    )


def init_all_telemetry(
    app: SupportsState | None = None,
    *,
    service_name: str | None = None,
    service_version: str | None = None,
    install_flight_recorder: bool = True,
) -> None:
    """Initialize traces, metrics, and logs in one call."""
    init_otel(
        app,
        service_name=service_name,
        service_version=service_version,
        install_flight_recorder=install_flight_recorder,
    )
    if app is not None:
        instrument_fastapi(app)
    instrument_httpx()
    try:  # pragma: no cover - logging bridge optional
        resolved_name = service_name or os.getenv("CODEINTEL_OTEL_SERVICE_NAME", "codeintel-mcp")
        init_otel_logging(service_name=resolved_name)
    except (RuntimeError, ValueError, OSError):  # pragma: no cover - defensive
        LOGGER.debug("Failed to initialize OpenTelemetry logs", exc_info=True)


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


def _current_span() -> object | None:
    trace_module = _STATE.trace_module or _optional_import("opentelemetry.trace")
    if trace_module is None:
        return None
    getter = getattr(trace_module, "get_current_span", None)
    if getter is None:
        return None
    try:
        return getter()
    except (RuntimeError, ValueError):  # pragma: no cover - defensive
        return None


def set_current_span_attrs(**attrs: object) -> None:
    """Attach attributes to the active span when tracing is enabled."""
    span = _current_span()
    if span is None:
        return
    setter = getattr(span, "set_attribute", None)
    if setter is None:
        return
    for key, value in _sanitize_span_attrs(attrs).items():
        try:
            setter(key, value)
        except (RuntimeError, ValueError, TypeError) as exc:  # pragma: no cover - defensive
            LOGGER.debug("Failed to set span attribute %s", key, exc_info=exc)
            continue


def _current_span_context() -> object | None:
    span = _current_span()
    if span is None:
        return None
    getter = getattr(span, "get_span_context", None)
    if getter is None:
        return None
    try:
        return getter()
    except (RuntimeError, ValueError):  # pragma: no cover - defensive
        return None


def current_trace_id() -> str | None:
    """Return the hex trace identifier for the active span.

    Returns
    -------
    str | None
        Hexadecimal trace ID string (32 characters) for the active span, or
        ``None`` if no active span is available or the trace ID is invalid.
    """
    context = _current_span_context()
    trace_id = getattr(context, "trace_id", 0)
    if not trace_id:
        return None
    return f"{int(trace_id):032x}"


def current_span_id() -> str | None:
    """Return the hex span identifier for the active span.

    Returns
    -------
    str | None
        Hexadecimal span ID string (16 characters) for the active span, or
        ``None`` if no active span is available or the span ID is invalid.
    """
    context = _current_span_context()
    span_id = getattr(context, "span_id", 0)
    if not span_id:
        return None
    return f"{int(span_id):016x}"


def _install_logging_instrumentation() -> None:
    if _STATE.logging_instrumented:
        return
    module = _optional_import("opentelemetry.instrumentation.logging")
    if module is None:
        return
    instrumentor = getattr(module, "LoggingInstrumentor", None)
    if instrumentor is None:
        return
    with suppress(Exception):  # pragma: no cover - defensive
        instrumentor().instrument(set_logging_format=True)
        _STATE.logging_instrumented = True


def _install_metrics_provider(resource: object, endpoint: str | None) -> None:
    """Configure OTLP/Prometheus metric readers when SDK components are present."""
    if _STATE.metrics_initialized:
        return
    try:
        metrics_module = importlib.import_module("opentelemetry.sdk.metrics")
        view_module = importlib.import_module("opentelemetry.sdk.metrics.view")
        export_module = importlib.import_module("opentelemetry.sdk.metrics.export")
        metrics_api = importlib.import_module("opentelemetry.metrics")
    except ImportError:  # pragma: no cover - optional dependency
        LOGGER.debug("OpenTelemetry metrics SDK unavailable; skipping metric provider setup")
        return
    metric_readers: list[object] = []
    exporter_endpoint = endpoint or os.getenv("CODEINTEL_OTEL_METRICS_ENDPOINT")
    if exporter_endpoint:
        try:
            exporter_module = importlib.import_module(
                "opentelemetry.exporter.otlp.proto.http.metric_exporter"
            )
        except ImportError:  # pragma: no cover - optional dependency
            LOGGER.debug("OTLP metric exporter unavailable; skipping OTLP reader")
        else:
            try:
                exporter = exporter_module.OTLPMetricExporter(endpoint=exporter_endpoint)
                reader_cls = getattr(export_module, "PeriodicExportingMetricReader", None)
                if reader_cls is not None:
                    metric_readers.append(reader_cls(exporter))
            except (RuntimeError, TypeError, ValueError):  # pragma: no cover - defensive
                LOGGER.debug("Failed to configure OTLP metric exporter", exc_info=True)
    if _env_flag("CODEINTEL_OTEL_PROMETHEUS_ENABLED", default=True):
        reader = _build_prometheus_reader()
        if reader is not None:
            metric_readers.append(reader)
            _start_prometheus_http_server()
    if not metric_readers:
        LOGGER.debug("No metric readers configured; skipping meter provider setup")
        return
    views = _build_metric_views(view_module, export_module)
    try:
        provider = metrics_module.MeterProvider(
            resource=resource,
            metric_readers=metric_readers,
            views=views or None,
        )
        metrics_api.set_meter_provider(provider)
        _STATE.metrics_initialized = True
    except (RuntimeError, ValueError):  # pragma: no cover - defensive
        LOGGER.debug("Failed to configure meter provider", exc_info=True)


def _build_prometheus_reader() -> object | None:
    """Return a PrometheusMetricReader when exporter is installed.

    Returns
    -------
    object | None
        Reader instance or ``None`` when unavailable.
    """
    module = _optional_import("opentelemetry.exporter.prometheus")
    if module is None:
        return None
    reader_cls = getattr(module, "PrometheusMetricReader", None)
    if reader_cls is None:
        return None
    try:
        return reader_cls()
    except (RuntimeError, ValueError, TypeError):  # pragma: no cover - defensive
        LOGGER.debug("PrometheusMetricReader construction failed", exc_info=True)
        return None


def _start_prometheus_http_server() -> None:
    """Expose the default Prometheus registry when supported."""
    if _STATE.prometheus_running or _prom_start_http_server is None:
        return
    host = os.getenv("CODEINTEL_OTEL_PROMETHEUS_HOST", os.getenv("PROMETHEUS_HOST", "127.0.0.1"))
    raw_port = os.getenv("CODEINTEL_OTEL_PROMETHEUS_PORT", os.getenv("PROMETHEUS_PORT", "9464"))
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        port = 9464
    try:
        _prom_start_http_server(port=port, addr=host)
        LOGGER.info("Prometheus scrape endpoint listening", extra={"host": host, "port": port})
        _STATE.prometheus_running = True
    except OSError:  # pragma: no cover - defensive
        LOGGER.warning("Failed to start Prometheus HTTP server", exc_info=True)


def _build_metric_views(view_module: ModuleType, export_module: ModuleType) -> list[object]:
    """Return default metric views for latency/counter instruments.

    Returns
    -------
    list[object]
        Collection of :class:`View` instances configuring histogram buckets and attributes.
    """
    view_cls = getattr(view_module, "View", None)
    histogram_cls = getattr(export_module, "ExplicitBucketHistogramAggregation", None)
    if view_cls is None or histogram_cls is None:
        return []
    bucket_defs = [
        (
            "codeintel_mcp_request_latency_seconds",
            [0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
            ("tool", "status"),
        ),
        (
            "codeintel_embed_latency_seconds",
            [0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10],
            (),
        ),
        (
            "codeintel_faiss_search_latency_seconds",
            [0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1, 2],
            (),
        ),
        (
            "codeintel_rerank_exact_latency_ms",
            [1, 5, 10, 25, 50, 100, 250, 500],
            (),
        ),
    ]
    views: list[object] = []
    for instrument_name, buckets, attrs in bucket_defs:
        kwargs: dict[str, object] = {
            "instrument_name": instrument_name,
            "aggregation": histogram_cls(buckets),
        }
        if attrs:
            kwargs["attribute_keys"] = attrs
        views.append(view_cls(**kwargs))
    return views


def instrument_fastapi(app: SupportsState) -> None:
    """Instrument FastAPI routes when instrumentation packages are installed."""
    if _STATE.fastapi_instrumented or not _STATE.tracing_enabled:
        return
    module = _optional_import("opentelemetry.instrumentation.fastapi")
    if module is None:
        return
    instrumentor = getattr(module, "FastAPIInstrumentor", None)
    if instrumentor is None:
        return
    with suppress(Exception):  # pragma: no cover - defensive
        instrumentor.instrument_app(app)
        _STATE.fastapi_instrumented = True


def instrument_httpx() -> None:
    """Instrument httpx clients when instrumentation packages are installed."""
    if _STATE.httpx_instrumented or not _STATE.tracing_enabled:
        return
    module = _optional_import("opentelemetry.instrumentation.httpx")
    if module is None:
        return
    instrumentor = getattr(module, "HTTPXClientInstrumentor", None)
    if instrumentor is None:
        return
    with suppress(Exception):  # pragma: no cover - defensive
        instrumentor().instrument()
        _STATE.httpx_instrumented = True


__all__ = [
    "as_span",
    "current_span_id",
    "current_trace_id",
    "init_all_telemetry",
    "init_otel",
    "init_telemetry",
    "instrument_fastapi",
    "instrument_httpx",
    "record_span_event",
    "set_current_span_attrs",
    "telemetry_enabled",
]
