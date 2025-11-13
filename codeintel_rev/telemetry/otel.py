"""OpenTelemetry bootstrap helpers for CodeIntel."""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from importlib import metadata
from types import ModuleType
from typing import Protocol, cast

from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)


class _TraceAPI(Protocol):
    def set_tracer_provider(self, provider: object) -> None:
        """Set the global tracer provider for OpenTelemetry tracing.

        Parameters
        ----------
        provider : object
            The TracerProvider instance to set as the global provider. This
            provider will be used for all subsequent trace operations in the
            application. The provider manages span processors and resource
            configuration.

        Notes
        -----
        This method sets the global tracer provider for the OpenTelemetry
        trace API. Once set, all trace operations will use this provider.
        """
        ...


class _MetricsAPI(Protocol):
    def set_meter_provider(self, provider: object) -> None:
        """Set the global meter provider for OpenTelemetry metrics.

        Parameters
        ----------
        provider : object
            The MeterProvider instance to set as the global provider. This
            provider will be used for all subsequent metric operations in the
            application. The provider manages metric readers and resource
            configuration.

        Notes
        -----
        This method sets the global meter provider for the OpenTelemetry
        metrics API. Once set, all metric operations will use this provider.
        """
        ...


class _TracerProviderInstance(Protocol):
    def add_span_processor(self, processor: object) -> None:
        """Add a span processor to the tracer provider.

        Parameters
        ----------
        processor : object
            The SpanProcessor instance to add. Span processors handle span
            export, batching, and processing. Common processors include
            BatchSpanProcessor for batching spans before export and
            SimpleSpanProcessor for immediate export.

        Notes
        -----
        Span processors are responsible for processing completed spans,
        including exporting them to backends (e.g., OTLP, console) and
        applying batching or sampling policies. Multiple processors can be
        added to a single provider.
        """
        ...


class _TracerProviderFactory(Protocol):
    def __call__(self, *args: object, **kwargs: object) -> _TracerProviderInstance: ...


class _Factory(Protocol):
    def __call__(self, *args: object, **kwargs: object) -> object: ...


class _ResourceFactory(Protocol):
    @classmethod
    def create(cls, attributes: dict[str, object]) -> object:
        """Create an OpenTelemetry Resource from attributes.

        Parameters
        ----------
        attributes : dict[str, object]
            Dictionary of resource attributes (key-value pairs) describing
            the service, deployment, or process. Common attributes include
            "service.name", "service.version", "deployment.environment", etc.
            These attributes are attached to all spans and metrics produced
            by the application.

        Returns
        -------
        object
            OpenTelemetry Resource instance containing the provided attributes.
            The Resource identifies the service/process in distributed tracing
            and metrics, allowing backends to filter and group telemetry data.

        Notes
        -----
        Resources are immutable and describe the entity producing telemetry
        (service, process, container, etc.). All spans and metrics produced
        by the application will include these resource attributes.
        """
        ...


def _optional_import(module: str) -> ModuleType | None:
    try:
        return importlib.import_module(module)
    except ImportError:  # pragma: no cover - optional dependency
        return None


def _import_attr(module: str, attr: str) -> object | None:
    mod = _optional_import(module)
    if mod is None:
        return None
    return getattr(mod, attr, None)


otel_metrics = cast("_MetricsAPI | None", _optional_import("opentelemetry.metrics"))
otel_trace = cast("_TraceAPI | None", _optional_import("opentelemetry.trace"))
OTLPMetricExporter = cast(
    "_Factory | None",
    _import_attr("opentelemetry.exporter.otlp.proto.http.metric_exporter", "OTLPMetricExporter"),
)
OTLPSpanExporter = cast(
    "_Factory | None",
    _import_attr("opentelemetry.exporter.otlp.proto.http.trace_exporter", "OTLPSpanExporter"),
)
MeterProvider = cast(
    "_Factory | None",
    _import_attr("opentelemetry.sdk.metrics", "MeterProvider"),
)
PeriodicExportingMetricReader = cast(
    "_Factory | None",
    _import_attr("opentelemetry.sdk.metrics.export", "PeriodicExportingMetricReader"),
)
ConsoleMetricExporter = cast(
    "_Factory | None",
    _import_attr("opentelemetry.sdk.metrics.export", "ConsoleMetricExporter"),
)
Resource = cast(
    "_ResourceFactory | None",
    _import_attr("opentelemetry.sdk.resources", "Resource"),
)
TracerProvider = cast(
    "_TracerProviderFactory | None",
    _import_attr("opentelemetry.sdk.trace", "TracerProvider"),
)
BatchSpanProcessor = cast(
    "_Factory | None",
    _import_attr("opentelemetry.sdk.trace.export", "BatchSpanProcessor"),
)
ConsoleSpanExporter = cast(
    "_Factory | None",
    _import_attr("opentelemetry.sdk.trace.export", "ConsoleSpanExporter"),
)


_INSTALL_STATE: dict[str, bool] = {"traces": False, "metrics": False}


@dataclass(slots=True, frozen=True)
class OtelInstallResult:
    """Summary describing which signal providers were installed."""

    traces: bool
    metrics: bool


@dataclass(slots=True, frozen=True)
class _TelemetryDeps:
    trace_api: _TraceAPI
    metrics_api: _MetricsAPI
    tracer_provider_factory: _TracerProviderFactory
    meter_provider_factory: _Factory
    metric_reader_factory: _Factory
    span_processor_factory: _Factory
    console_span_exporter_factory: _Factory
    console_metric_exporter_factory: _Factory


def _resolve_factories() -> _TelemetryDeps:
    components = (
        otel_trace,
        otel_metrics,
        MeterProvider,
        PeriodicExportingMetricReader,
        TracerProvider,
        BatchSpanProcessor,
        ConsoleSpanExporter,
        ConsoleMetricExporter,
    )
    if any(component is None for component in components):
        msg = "OpenTelemetry SDK not available; telemetry disabled"
        raise RuntimeError(msg)
    return _TelemetryDeps(
        trace_api=cast("_TraceAPI", otel_trace),
        metrics_api=cast("_MetricsAPI", otel_metrics),
        tracer_provider_factory=cast("_TracerProviderFactory", TracerProvider),
        meter_provider_factory=cast("_Factory", MeterProvider),
        metric_reader_factory=cast("_Factory", PeriodicExportingMetricReader),
        span_processor_factory=cast("_Factory", BatchSpanProcessor),
        console_span_exporter_factory=cast("_Factory", ConsoleSpanExporter),
        console_metric_exporter_factory=cast("_Factory", ConsoleMetricExporter),
    )


def _env_flag(name: str, *, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _service_version() -> str | None:
    for pkg in ("kgfoundry", "codeintel-rev"):
        try:
            return metadata.version(pkg)
        except metadata.PackageNotFoundError:
            continue
    return None


def build_resource(
    *,
    service_name: str,
    service_version: str | None = None,
    environment: str | None = None,
) -> object:
    """Build an OpenTelemetry Resource describing this process.

    This function constructs an OpenTelemetry Resource object with service metadata
    (name, version, environment) extracted from parameters or environment variables.
    The Resource is used to identify the service in distributed tracing and metrics.

    Parameters
    ----------
    service_name : str
        Service identifier used in OpenTelemetry Resource attributes. Required
        parameter that identifies the service name (e.g., "codeintel-mcp").
    service_version : str | None, optional
        Optional service version string (default: None). When provided, added to
        Resource attributes as "service.version". Used to track service versions
        in telemetry data.
    environment : str | None, optional
        Optional deployment environment identifier (default: None). When provided,
        added to Resource attributes as "deployment.environment". Falls back to
        DEPLOYMENT_ENVIRONMENT or ENVIRONMENT environment variables if not provided.
        Used to distinguish between dev/staging/production environments.

    Returns
    -------
    object
        OpenTelemetry ``Resource`` instance describing the current process. The
        Resource contains service metadata (name, version, environment) extracted
        from parameters and environment variables.

    Raises
    ------
    RuntimeError
        Raised when the OpenTelemetry Resource class is unavailable (OpenTelemetry
        SDK not installed or import failed).
    """
    if Resource is None:  # pragma: no cover - defensive
        msg = "OpenTelemetry Resource type unavailable"
        raise RuntimeError(msg)

    attrs: dict[str, object] = {"service.name": service_name}
    if service_version:
        attrs["service.version"] = service_version
    env = environment or os.getenv("DEPLOYMENT_ENVIRONMENT") or os.getenv("ENVIRONMENT")
    if env:
        attrs["deployment.environment"] = env
    namespace = os.getenv("SERVICE_NAMESPACE")
    if namespace:
        attrs["service.namespace"] = namespace
    instance_id = os.getenv("HOSTNAME") or os.getenv("POD_NAME")
    if instance_id:
        attrs["service.instance.id"] = instance_id
    resource_cls: _ResourceFactory = Resource
    return resource_cls.create(attrs)


def _build_span_exporter(endpoint: str | None, *, insecure: bool) -> object | None:
    if endpoint is None or OTLPSpanExporter is None:
        return None
    return OTLPSpanExporter(endpoint=endpoint, insecure=insecure)


def _build_metric_exporter(endpoint: str | None, *, insecure: bool) -> object | None:
    if endpoint is None or OTLPMetricExporter is None:
        return None
    return OTLPMetricExporter(endpoint=endpoint, insecure=insecure)


def install_otel(
    *,
    service_name: str | None = None,
    service_version: str | None = None,
    environment: str | None = None,
) -> OtelInstallResult:
    """Install tracer/meter providers with console fallbacks.

    This function installs OpenTelemetry trace and metric providers for the
    application, with graceful fallback when OpenTelemetry SDK is unavailable.
    The function configures global providers and returns installation status.

    Parameters
    ----------
    service_name : str | None, optional
        Optional service name for OpenTelemetry Resource (default: None). When None,
        falls back to OTEL_SERVICE_NAME environment variable or "codeintel-mcp".
        Used to identify the service in distributed tracing and metrics.
    service_version : str | None, optional
        Optional service version string (default: None). When None, attempts to
        detect version from package metadata or environment. Used to track service
        versions in telemetry data.
    environment : str | None, optional
        Optional deployment environment identifier (default: None). When None,
        falls back to DEPLOYMENT_ENVIRONMENT or ENVIRONMENT environment variables.
        Used to distinguish between dev/staging/production environments.

    Returns
    -------
    OtelInstallResult
        Flags indicating whether trace and metric providers were installed.
        Returns OtelInstallResult(traces=True, metrics=True) when installation
        succeeds, or OtelInstallResult(traces=False, metrics=False) when
        OpenTelemetry SDK is unavailable or telemetry is disabled.
    """
    if _INSTALL_STATE["traces"] and _INSTALL_STATE["metrics"]:
        return OtelInstallResult(traces=True, metrics=True)
    if not _env_flag("TELEMETRY_ENABLED", default=True):
        LOGGER.info("Telemetry disabled via TELEMETRY_ENABLED=0")
        return OtelInstallResult(traces=False, metrics=False)
    try:
        deps = _resolve_factories()
    except RuntimeError:
        LOGGER.warning("OpenTelemetry SDK not available; telemetry disabled")
        return OtelInstallResult(traces=False, metrics=False)

    resource = build_resource(
        service_name=service_name or os.getenv("OTEL_SERVICE_NAME", "codeintel-mcp"),
        service_version=service_version or _service_version(),
        environment=environment,
    )
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    insecure = _env_flag("OTEL_EXPORTER_OTLP_INSECURE", default=True)

    span_exporter = _build_span_exporter(endpoint, insecure=insecure)
    trace_provider = deps.tracer_provider_factory(resource=resource)
    if span_exporter is not None:
        trace_provider.add_span_processor(deps.span_processor_factory(span_exporter))
    else:
        console_span_exporter = deps.console_span_exporter_factory()
        trace_provider.add_span_processor(deps.span_processor_factory(console_span_exporter))
    deps.trace_api.set_tracer_provider(trace_provider)
    _INSTALL_STATE["traces"] = True

    metric_exporter = _build_metric_exporter(endpoint, insecure=insecure)
    readers: list[object] = []
    if metric_exporter is not None:
        readers.append(deps.metric_reader_factory(metric_exporter))
    else:
        console_metric_exporter = deps.console_metric_exporter_factory()
        readers.append(deps.metric_reader_factory(console_metric_exporter))
    meter_provider = deps.meter_provider_factory(resource=resource, metric_readers=readers)
    deps.metrics_api.set_meter_provider(meter_provider)
    _INSTALL_STATE["metrics"] = True

    return OtelInstallResult(traces=True, metrics=True)
