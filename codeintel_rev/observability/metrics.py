"""Telemetry metrics registry and OpenTelemetry Meter bootstrap."""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from kgfoundry_common.logging import get_logger

from codeintel_rev.telemetry.otel_metrics import build_counter, build_gauge, build_histogram

if TYPE_CHECKING:
    from opentelemetry.sdk.resources import Resource
else:  # pragma: no cover - typing only
    Resource = Any

LOGGER = get_logger(__name__)
_METRICS_PROVIDER_INSTALLED = False
_PROM_HTTP_SERVER_STARTED = False

try:  # pragma: no cover - optional dependency
    from prometheus_client import start_http_server as _prom_start_http_server
except ImportError:  # pragma: no cover - optional dependency
    _prom_start_http_server = None


def _env_flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _import_module(name: str) -> Any | None:
    try:
        return importlib.import_module(name)
    except ImportError:  # pragma: no cover - optional dependency
        return None


def _build_metric_views(view_module: Any, export_module: Any) -> list[Any]:
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
    views: list[Any] = []
    for instrument_name, buckets, attrs in bucket_defs:
        kwargs: dict[str, object] = {
            "instrument_name": instrument_name,
            "aggregation": histogram_cls(buckets),
        }
        if attrs:
            kwargs["attribute_keys"] = attrs
        views.append(view_cls(**kwargs))
    return views


def _build_prometheus_reader() -> Any | None:
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
    global _PROM_HTTP_SERVER_STARTED
    if _PROM_HTTP_SERVER_STARTED or _prom_start_http_server is None:
        return
    host = os.getenv("CODEINTEL_OTEL_PROMETHEUS_HOST", os.getenv("PROMETHEUS_HOST", "0.0.0.0"))
    try:
        port = int(os.getenv("CODEINTEL_OTEL_PROMETHEUS_PORT", os.getenv("PROMETHEUS_PORT", "9464")))
    except (TypeError, ValueError):
        port = 9464
    try:
        _prom_start_http_server(port=port, addr=host)
    except OSError:  # pragma: no cover - defensive
        LOGGER.warning("Failed to start Prometheus HTTP server", exc_info=True)
    else:
        _PROM_HTTP_SERVER_STARTED = True
        LOGGER.info("Prometheus scrape endpoint listening", extra={"host": host, "port": port})


def install_metrics_provider(resource: Resource, *, otlp_endpoint: str | None = None) -> None:
    """Install a global MeterProvider with OTLP + Prometheus readers."""
    global _METRICS_PROVIDER_INSTALLED
    if _METRICS_PROVIDER_INSTALLED:
        return
    metrics_sdk = _import_module("opentelemetry.sdk.metrics")
    view_module = _import_module("opentelemetry.sdk.metrics.view")
    export_module = _import_module("opentelemetry.sdk.metrics.export")
    metrics_api = _import_module("opentelemetry.metrics")
    if None in (metrics_sdk, view_module, export_module, metrics_api):
        LOGGER.debug("OpenTelemetry metrics components unavailable; skipping meter install")
        return
    metric_readers: list[Any] = []
    endpoint = otlp_endpoint or os.getenv("CODEINTEL_OTEL_METRICS_ENDPOINT")
    if endpoint:
        exporter_module = _import_module("opentelemetry.exporter.otlp.proto.http.metric_exporter")
        reader_cls = getattr(export_module, "PeriodicExportingMetricReader", None)
        if exporter_module is None or reader_cls is None:
            LOGGER.debug("OTLP metric exporter unavailable; skipping OTLP reader")
        else:
            try:
                exporter = exporter_module.OTLPMetricExporter(endpoint=endpoint)
                metric_readers.append(reader_cls(exporter))
            except (RuntimeError, ValueError, TypeError, OSError):  # pragma: no cover - defensive
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
        provider = metrics_sdk.MeterProvider(
            resource=resource,
            metric_readers=metric_readers,
            views=views or None,
        )
        metrics_api.set_meter_provider(provider)
    except (RuntimeError, ValueError):  # pragma: no cover - defensive
        LOGGER.debug("Failed to install meter provider", exc_info=True)
        return
    _METRICS_PROVIDER_INSTALLED = True


__all__ = [
    "install_metrics_provider",
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
