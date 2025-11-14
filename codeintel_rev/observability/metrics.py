"""Telemetry metrics registry and OpenTelemetry Meter bootstrap."""

from __future__ import annotations

import importlib
import os
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from types import ModuleType
from typing import TYPE_CHECKING

from codeintel_rev.telemetry.otel_metrics import build_counter, build_gauge, build_histogram
from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    from opentelemetry.sdk.metrics.export import MetricReader
    from opentelemetry.sdk.metrics.view import View
    from opentelemetry.sdk.resources import Resource

LOGGER = get_logger(__name__)


@dataclass(slots=True, frozen=False)
class _MetricsState:
    """Thread-safe metrics provider state."""

    provider_installed: bool = False
    prom_server_started: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


_METRICS_STATE = _MetricsState()

try:  # pragma: no cover - optional dependency
    from prometheus_client import start_http_server as _prom_start_http_server
except ImportError:  # pragma: no cover - optional dependency
    _prom_start_http_server = None


def _env_flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _import_module(name: str) -> ModuleType | None:
    """Import a module by name, returning None if unavailable.

    Parameters
    ----------
    name : str
        Module name to import (e.g., "opentelemetry.sdk.metrics").

    Returns
    -------
    ModuleType | None
        Imported module if available, otherwise None.
    """
    try:
        return importlib.import_module(name)
    except ImportError:  # pragma: no cover - optional dependency
        return None


def _build_metric_views(
    view_module: ModuleType,
    export_module: ModuleType,
) -> list[View]:
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
            "codeintel_duckdb_execute_seconds",
            [0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5],
            (),
        ),
    ]
    views: list[View] = []
    for instrument_name, buckets, attrs in bucket_defs:
        if histogram_cls is None or view_cls is None:
            continue
        aggregation = histogram_cls(buckets)
        kwargs: dict[str, object] = {
            "instrument_name": instrument_name,
            "aggregation": aggregation,
        }
        if attrs:
            kwargs["attribute_keys"] = attrs
        view_instance = view_cls(**kwargs)
        views.append(view_instance)
    return views


def _build_prometheus_reader() -> MetricReader | None:
    exporter_module = _import_module("opentelemetry.exporter.prometheus")
    if exporter_module is None:
        return None
    reader_cls = getattr(exporter_module, "PrometheusMetricReader", None)
    if reader_cls is None:
        return None
    try:
        return reader_cls(prefix="codeintel")
    except (RuntimeError, TypeError, ValueError):  # pragma: no cover - defensive
        LOGGER.debug("PrometheusMetricReader construction failed", exc_info=True)
        return None


def _start_prometheus_http_server() -> None:
    """Start Prometheus HTTP server for metrics scraping (idempotent)."""
    with _METRICS_STATE.lock:
        if _METRICS_STATE.prom_server_started or _prom_start_http_server is None:
            return
        # Binding to 0.0.0.0 is intentional for Prometheus scraping
        host = os.getenv(
            "CODEINTEL_OTEL_PROMETHEUS_HOST",
            os.getenv("PROMETHEUS_HOST", "0.0.0.0"),  # noqa: S104
        )
        try:
            port = int(
                os.getenv(
                    "CODEINTEL_OTEL_PROMETHEUS_PORT",
                    os.getenv("PROMETHEUS_PORT", "9464"),
                )
            )
        except (TypeError, ValueError):
            port = 9464
        try:
            _prom_start_http_server(port=port, addr=host)
        except OSError:  # pragma: no cover - defensive
            LOGGER.warning("Failed to start Prometheus HTTP server", exc_info=True)
        else:
            _METRICS_STATE.prom_server_started = True
            LOGGER.info(
                "Prometheus scrape endpoint listening",
                extra={"host": host, "port": port},
            )


def _load_metrics_modules() -> tuple[ModuleType, ModuleType, ModuleType, ModuleType] | None:
    """Load all required metrics SDK modules.

    Returns
    -------
    tuple[ModuleType, ModuleType, ModuleType, ModuleType] | None
        Tuple of (sdk, view, export, api) modules if all available, otherwise None.
    """
    metrics_sdk = _import_module("opentelemetry.sdk.metrics")
    view_module = _import_module("opentelemetry.sdk.metrics.view")
    export_module = _import_module("opentelemetry.sdk.metrics.export")
    metrics_api = _import_module("opentelemetry.metrics")
    required_modules = {metrics_sdk, view_module, export_module, metrics_api}
    if None in required_modules:
        return None
    # Type narrowing: we know these are not None after the check
    if metrics_sdk is None or view_module is None or export_module is None or metrics_api is None:
        return None  # Defensive check (should not happen after set check)
    return (metrics_sdk, view_module, export_module, metrics_api)


def _build_otlp_reader(
    export_module: ModuleType,
    endpoint: str,
) -> MetricReader | None:
    """Build OTLP metric reader if available.

    Parameters
    ----------
    export_module : ModuleType
        OpenTelemetry export module.
    endpoint : str
        OTLP endpoint URL.

    Returns
    -------
    MetricReader | None
        OTLP reader instance if available, otherwise None.
    """
    exporter_module = _import_module("opentelemetry.exporter.otlp.proto.http.metric_exporter")
    reader_cls = getattr(export_module, "PeriodicExportingMetricReader", None)
    if exporter_module is None or reader_cls is None:
        return None
    try:
        exporter_cls = getattr(exporter_module, "OTLPMetricExporter", None)
        if exporter_cls is not None:
            exporter = exporter_cls(endpoint=endpoint)
            return reader_cls(exporter)
    except (RuntimeError, ValueError, TypeError, OSError):  # pragma: no cover - defensive
        LOGGER.debug("Failed to configure OTLP metric exporter", exc_info=True)
    return None


def install_metrics_provider(resource: Resource, *, otlp_endpoint: str | None = None) -> None:
    """Install a global MeterProvider with OTLP + Prometheus readers.

    Parameters
    ----------
    resource : Resource
        OpenTelemetry Resource instance containing service metadata.
    otlp_endpoint : str | None, optional
        Optional OTLP endpoint override. Defaults to environment variable.
    """
    with _METRICS_STATE.lock:
        if _METRICS_STATE.provider_installed:
            return
        modules = _load_metrics_modules()
        if modules is None:
            LOGGER.debug("OpenTelemetry metrics components unavailable; skipping meter install")
            return
        metrics_sdk, view_module, export_module, metrics_api = modules

        metric_readers: list[MetricReader] = []
        endpoint = otlp_endpoint or os.getenv("CODEINTEL_OTEL_METRICS_ENDPOINT")
        if endpoint:
            reader = _build_otlp_reader(export_module, endpoint)
            if reader is not None:
                metric_readers.append(reader)
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
            provider_cls = getattr(metrics_sdk, "MeterProvider", None)
            set_provider_fn = getattr(metrics_api, "set_meter_provider", None)
            if provider_cls is not None and set_provider_fn is not None:
                provider = provider_cls(
                    resource=resource,
                    metric_readers=metric_readers,
                    views=views or None,
                )
                set_provider_fn(provider)
        except (RuntimeError, ValueError):  # pragma: no cover - defensive
            LOGGER.debug("Failed to install meter provider", exc_info=True)
            return
        _METRICS_STATE.provider_installed = True


__all__ = [
    "BUDGET_DEPTH",
    "CHANNEL_LATENCY_SECONDS",
    "DEBUG_BUNDLE_TOTAL",
    "INDEX_VERSION_INFO",
    "QUERIES_TOTAL",
    "QUERY_AMBIGUITY",
    "QUERY_ERRORS_TOTAL",
    "RECALL_AT_K",
    "RECENCY_BOOSTED_TOTAL",
    "RESULTS_TOTAL",
    "RRF_DURATION_SECONDS",
    "RRF_K",
    "install_metrics_provider",
    "observe_budget_depths",
    "record_recall",
    "set_index_version",
]


QUERIES_TOTAL = build_counter(
    "codeintel_rev_queries_total",
    "Total retrieval requests",
    ("kind",),
)

QUERY_ERRORS_TOTAL = build_counter(
    "codeintel_rev_query_errors_total",
    "Failed retrieval requests",
    ("kind", "channel"),
)

RRF_DURATION_SECONDS = build_histogram(
    "codeintel_rev_rrf_duration_seconds",
    "RRF fusion latency (seconds)",
    unit="seconds",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0),
)

CHANNEL_LATENCY_SECONDS = build_histogram(
    "codeintel_rev_channel_duration_seconds",
    "Per-channel search latency (seconds)",
    labelnames=("channel",),
    unit="seconds",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0),
)

INDEX_VERSION_INFO = build_gauge(
    "codeintel_rev_index_version_info",
    "Active index version information",
    ("component",),
)

RRF_K = build_gauge(
    "codeintel_retrieval_rrf_k",
    "RRF K selected for fusion",
)

BUDGET_DEPTH = build_gauge(
    "codeintel_retrieval_budget_depth",
    "Channel depth selected by gating",
    ("channel",),
)

QUERY_AMBIGUITY = build_histogram(
    "codeintel_retrieval_query_ambiguity",
    "Heuristic ambiguity score for incoming queries",
    buckets=(0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0),
)

DEBUG_BUNDLE_TOTAL = build_counter(
    "codeintel_retrieval_debug_bundle_total",
    "Debug bundles emitted for hybrid retrieval",
)

RESULTS_TOTAL = build_counter(
    "codeintel_retrieval_results_total",
    "Total fused documents returned to clients",
)

RECENCY_BOOSTED_TOTAL = build_counter(
    "codeintel_retrieval_recency_boosted_total",
    "Documents receiving recency boost",
)

RECALL_AT_K = build_gauge(
    "codeintel_rev_recall_at_k",
    "Offline recall@k for golden queries",
    ("k",),
)


def observe_budget_depths(depths: Iterable[tuple[str, int]]) -> None:
    """Record per-channel depth decisions."""
    for channel, depth in depths:
        BUDGET_DEPTH.labels(channel=channel).set(float(depth))


def record_recall(k: int, value: float) -> None:
    """Record recall@k values produced by offline harnesses."""
    RECALL_AT_K.labels(k=str(k)).set(float(value))


def set_index_version(component: str, version: str | None) -> None:
    """Expose the current index version for dashboards.

    Parameters
    ----------
    component : str
        Component identifier ("faiss", "bm25", "splade").
    version : str | None
        Version string reported by the lifecycle manager. When the version
        cannot be parsed as a numeric value the gauge is set to ``0``.
    """
    numeric_value = 0.0
    if version:
        digits = "".join(char for char in version if char.isdigit())
        if digits:
            try:
                numeric_value = float(digits[:15])
            except ValueError:
                numeric_value = 0.0
    INDEX_VERSION_INFO.labels(component=component).set(numeric_value)
