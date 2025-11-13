"""OpenTelemetry bootstrap helpers for CodeIntel."""

from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import metadata
from typing import Any

try:  # pragma: no cover - optional dependency
    from opentelemetry import metrics as otel_metrics
    from opentelemetry import trace as otel_trace
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import (
        ConsoleMetricExporter,
        PeriodicExportingMetricReader,
    )
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
    )
except ImportError:  # pragma: no cover - graceful fallback when otel missing
    otel_metrics = None
    otel_trace = None
    OTLPMetricExporter = None
    OTLPSpanExporter = None
    MeterProvider = None
    PeriodicExportingMetricReader = None
    ConsoleMetricExporter = None
    BatchSpanProcessor = None
    ConsoleSpanExporter = None
    Resource = None
    TracerProvider = None

from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)


def _env_flag(name: str, *, default: bool = True) -> bool:
    """Return environment flag value.

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
        recognized as truthy (default: True). Used to provide fallback behavior
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


def _service_version() -> str | None:
    """Return package version for resource attributes.

    Returns
    -------
    str | None
        Installed package version or ``None`` if not resolved.
    """
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
) -> Resource:
    """Build an OpenTelemetry Resource describing this process.

    This function creates an OpenTelemetry Resource object that describes the
    service process for distributed tracing. The resource includes service name,
    version, and environment attributes that are attached to all exported spans.

    Parameters
    ----------
    service_name : str
        Name of the service for resource identification. Used as the primary
        identifier in traces and metrics. Should match the application name
        (e.g., "codeintel_rev").
    service_version : str | None, optional
        Version string for the service (default: None). When provided, included
        as a resource attribute. Useful for tracking deployments and version
        changes in traces.
    environment : str | None, optional
        Environment identifier (e.g., "production", "staging", "development")
        (default: None). When provided, included as a resource attribute for
        filtering and grouping traces by environment.

    Returns
    -------
    Resource
        OpenTelemetry Resource object describing the service with name, version,
        and environment attributes. The resource is attached to all spans exported
        by this process.

    Raises
    ------
    RuntimeError
        Raised when the Resource type is unavailable.
    """
    if Resource is None:  # pragma: no cover - defensive
        msg = "OpenTelemetry Resource type unavailable"
        raise RuntimeError(msg)

    attrs: dict[str, Any] = {"service.name": service_name}
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
    return Resource.create(attrs)


_TRACE_INSTALLED = False
_METRICS_INSTALLED = False


@dataclass(slots=True, frozen=True)
class OtelInstallResult:
    """Summary describing which signal providers were installed."""

    traces: bool
    metrics: bool


def _build_span_exporter(endpoint: str | None, *, insecure: bool) -> object | None:
    """Return an OTLP span exporter when configured.

    This function creates an OTLP (OpenTelemetry Protocol) HTTP span exporter
    for exporting traces to an OTLP collector. The exporter is configured with
    the provided endpoint and security settings.

    Parameters
    ----------
    endpoint : str | None
        OTLP HTTP endpoint URL for span export (e.g., "https://collector:4318/v1/traces").
        When None, returns None without creating an exporter. Used to configure
        the destination for exported spans.
    insecure : bool
        Flag indicating whether to use insecure (HTTP) connections. When True,
        disables TLS verification for the OTLP endpoint. When False, uses secure
        HTTPS connections with certificate validation.

    Returns
    -------
    object | None
        OTLPSpanExporter instance when endpoint is provided and OTLP exporters
        are available, otherwise None. Returns None when endpoint is None or
        when OTLP exporter modules are not installed.
    """
    if endpoint is None or OTLPSpanExporter is None:
        return None
    return OTLPSpanExporter(endpoint=endpoint, insecure=insecure)


def _build_metric_exporter(endpoint: str | None, *, insecure: bool) -> object | None:
    """Return an OTLP metric exporter when configured.

    This function creates an OTLP (OpenTelemetry Protocol) HTTP metric exporter
    for exporting metrics to an OTLP collector. The exporter is configured with
    the provided endpoint and security settings.

    Parameters
    ----------
    endpoint : str | None
        OTLP HTTP endpoint URL for metric export (e.g., "https://collector:4318/v1/metrics").
        When None, returns None without creating an exporter. Used to configure
        the destination for exported metrics.
    insecure : bool
        Flag indicating whether to use insecure (HTTP) connections. When True,
        disables TLS verification for the OTLP endpoint. When False, uses secure
        HTTPS connections with certificate validation.

    Returns
    -------
    object | None
        OTLPMetricExporter instance when endpoint is provided and OTLP exporters
        are available, otherwise None. Returns None when endpoint is None or
        when OTLP exporter modules are not installed.
    """
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

    This function initializes OpenTelemetry tracing and metrics providers with
    OTLP exporters (when configured) or console exporters as fallbacks. The function
    sets up resource attributes, configures span processors, and enables telemetry
    for the application lifecycle.

    Parameters
    ----------
    service_name : str | None, optional
        Service name for resource identification (default: None). When None, uses
        a default service name. Used as the primary identifier in traces and
        metrics. Should match the application name.
    service_version : str | None, optional
        Service version string for resource attributes (default: None). When
        provided, included in the OpenTelemetry resource. Useful for tracking
        deployments and version changes in traces.
    environment : str | None, optional
        Environment identifier (e.g., "production", "staging", "development")
        (default: None). When provided, included in the OpenTelemetry resource
        for filtering and grouping traces by environment.

    Returns
    -------
    OtelInstallResult
        Outcome object describing which providers were successfully initialized.
        Contains traces and metrics boolean flags indicating whether each provider
        type was installed. Both flags are True when telemetry is fully enabled.
    """
    global _TRACE_INSTALLED, _METRICS_INSTALLED  # noqa: PLW0603

    if _TRACE_INSTALLED and _METRICS_INSTALLED:
        return OtelInstallResult(traces=True, metrics=True)
    if not _env_flag("TELEMETRY_ENABLED", default=True):
        LOGGER.info("Telemetry disabled via TELEMETRY_ENABLED=0")
        return OtelInstallResult(traces=False, metrics=False)
    if any(
        component is None
        for component in (
            otel_metrics,
            otel_trace,
            MeterProvider,
            PeriodicExportingMetricReader,
            TracerProvider,
            BatchSpanProcessor,
            ConsoleSpanExporter,
            ConsoleMetricExporter,
        )
    ):
        LOGGER.warning("OpenTelemetry SDK not available; telemetry disabled")
        return OtelInstallResult(traces=False, metrics=False)

    resource = build_resource(
        service_name=service_name or os.getenv("OTEL_SERVICE_NAME", "codeintel-mcp"),
        service_version=service_version or _service_version(),
        environment=environment,
    )
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    insecure = _env_flag("OTEL_EXPORTER_OTLP_INSECURE", default=True)

    # ----- Traces -----
    span_exporter = _build_span_exporter(endpoint, insecure=insecure)
    trace_provider = TracerProvider(resource=resource)
    if span_exporter is not None:
        trace_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    else:
        trace_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    otel_trace.set_tracer_provider(trace_provider)
    _TRACE_INSTALLED = True

    # ----- Metrics -----
    metric_exporter = _build_metric_exporter(endpoint, insecure=insecure)
    readers = []
    if metric_exporter is not None:
        readers.append(PeriodicExportingMetricReader(metric_exporter))
    else:
        readers.append(PeriodicExportingMetricReader(ConsoleMetricExporter()))
    meter_provider = MeterProvider(resource=resource, metric_readers=readers)
    otel_metrics.set_meter_provider(meter_provider)
    _METRICS_INSTALLED = True

    return OtelInstallResult(traces=True, metrics=True)
