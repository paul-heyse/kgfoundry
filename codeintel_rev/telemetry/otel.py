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

    Returns
    -------
    bool
        Parsed boolean flag.
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

    Returns
    -------
    Resource
        OpenTelemetry resource describing the service.

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

    Returns
    -------
    object | None
        Span exporter instance or ``None`` when OTLP exporters are unavailable.
    """
    if endpoint is None or OTLPSpanExporter is None:
        return None
    return OTLPSpanExporter(endpoint=endpoint, insecure=insecure)


def _build_metric_exporter(endpoint: str | None, *, insecure: bool) -> object | None:
    """Return an OTLP metric exporter when configured.

    Returns
    -------
    object | None
        Metric exporter instance or ``None`` when OTLP exporters are unavailable.
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

    Returns
    -------
    OtelInstallResult
        Outcome describing which providers were initialised.
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
