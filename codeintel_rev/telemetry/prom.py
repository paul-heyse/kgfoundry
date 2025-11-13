"""Prometheus helpers for MCP diagnostics."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from kgfoundry_common.prometheus import (
    CollectorRegistry,
    build_counter,
    build_histogram,
    get_default_registry,
)

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import APIRouter
    from fastapi.responses import Response

try:  # pragma: no cover - optional dependency
    from fastapi import APIRouter as RuntimeAPIRouter
    from fastapi.responses import Response as RuntimeResponse
except ModuleNotFoundError:  # pragma: no cover - fallback for tests
    RuntimeAPIRouter = None
    RuntimeResponse = None


class _GenerateLatest(Protocol):
    def __call__(self, registry: CollectorRegistry = ..., escaping: str = ...) -> bytes: ...


try:  # pragma: no cover - optional dependency
    from prometheus_client import CONTENT_TYPE_LATEST as PROM_CONTENT_TYPE
    from prometheus_client import generate_latest as _prometheus_generate_latest_impl
except ImportError:  # pragma: no cover - fallback when prometheus missing
    PROM_CONTENT_TYPE = "text/plain; version=0.0.4"

    def _prometheus_generate_latest(registry: CollectorRegistry | None = None) -> bytes:
        if registry is not None:
            return b"# Registry provided but Prometheus client unavailable\n"
        return b"# Prometheus metrics unavailable (prometheus_client not installed)\n"
else:
    _prometheus_generate_latest_typed = cast(
        "_GenerateLatest",
        _prometheus_generate_latest_impl,
    )

    def _prometheus_generate_latest(registry: CollectorRegistry | None = None) -> bytes:
        if registry is None:
            return _prometheus_generate_latest_typed()
        return _prometheus_generate_latest_typed(registry)


CONTENT_TYPE_LATEST = PROM_CONTENT_TYPE


def generate_latest(registry: CollectorRegistry | None = None) -> bytes:
    """Proxy to prometheus_client.generate_latest with graceful fallback.

    This function generates OpenMetrics-formatted payload from Prometheus metrics
    registry. It provides a graceful fallback when prometheus_client is unavailable,
    returning an empty payload instead of raising an exception.

    Parameters
    ----------
    registry : CollectorRegistry | None, optional
        Optional Prometheus CollectorRegistry to scrape metrics from (default: None).
        When None, uses the default global registry. Used to generate metrics payload
        for scraping clients (e.g., Prometheus server).

    Returns
    -------
    bytes
        OpenMetrics payload for scraping clients. Returns empty bytes when
        prometheus_client is unavailable. The payload contains all metrics
        registered in the specified registry (or default registry if None).
    """
    if registry is None:
        return _prometheus_generate_latest()
    return _prometheus_generate_latest(registry)


__all__ = [
    "EMBED_BATCH_SIZE",
    "EMBED_LATENCY_SECONDS",
    "FAISS_SEARCH_LATENCY_SECONDS",
    "GATING_DECISIONS_TOTAL",
    "QUERY_AMBIGUITY",
    "RRFK",
    "XTR_SEARCH_LATENCY_SECONDS",
    "MetricsConfig",
    "build_metrics_router",
    "observe_request_latency",
    "record_run",
    "record_run_error",
    "record_stage_latency",
]


def _env_flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


RUNS_TOTAL = build_counter(
    "codeintel_runs_total",
    "Total MCP runs grouped by tool and status.",
    labelnames=("tool", "status"),
)

RUN_ERRORS_TOTAL = build_counter(
    "codeintel_run_errors_total",
    "Run errors grouped by tool and error code.",
    labelnames=("tool", "error_code"),
)

REQUEST_LATENCY_SECONDS = build_histogram(
    "codeintel_mcp_request_latency_seconds",
    "Per-request latency histogram.",
    labelnames=("tool", "status"),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

STAGE_LATENCY_SECONDS = build_histogram(
    "codeintel_search_stage_latency_seconds",
    "Latency per search stage.",
    labelnames=("stage",),
    buckets=(0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0),
)

EMBED_BATCH_SIZE = build_histogram(
    "codeintel_embed_batch_size",
    "Observed embedding batch sizes.",
    buckets=(1, 2, 4, 8, 16, 32, 64, 128, 256),
)

EMBED_LATENCY_SECONDS = build_histogram(
    "codeintel_embed_latency_seconds",
    "Latency of vLLM embed_batch invocations.",
    buckets=(0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)

FAISS_SEARCH_LATENCY_SECONDS = build_histogram(
    "codeintel_faiss_search_latency_seconds",
    "Latency of FAISS ANN searches.",
    buckets=(0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1, 2),
)

XTR_SEARCH_LATENCY_SECONDS = build_histogram(
    "codeintel_xtr_search_latency_seconds",
    "Latency of XTR search/rescore phases.",
    buckets=(0.005, 0.01, 0.02, 0.05, 0.1, 0.25, 0.5, 1, 2),
)

GATING_DECISIONS_TOTAL = build_counter(
    "codeintel_gating_decisions_total",
    "Count of gating/budgeting decisions.",
    labelnames=("klass", "rm3_enabled"),
)

RRFK = build_histogram(
    "codeintel_rrf_k",
    "Distribution of RRF k decisions.",
    buckets=(10, 25, 50, 75, 100, 150, 200, 300, 500),
)

QUERY_AMBIGUITY = build_histogram(
    "codeintel_query_ambiguity",
    "Distribution of query ambiguity scores.",
    buckets=(0.0, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0),
)


@dataclass(slots=True, frozen=True)
class MetricsConfig:
    """Configuration container for exposing `/metrics`."""

    enabled: bool = _env_flag("PROMETHEUS_ENABLED", default=True)
    registry: CollectorRegistry | None = None


def build_metrics_router(config: MetricsConfig | None = None) -> APIRouter | None:
    """Return an APIRouter exposing the Prometheus scrape endpoint.

    This function creates a FastAPI APIRouter that exposes a `/metrics` endpoint
    for Prometheus scraping. The router is configured with the provided metrics
    configuration and returns None when FastAPI or prometheus components are
    unavailable.

    Parameters
    ----------
    config : MetricsConfig | None, optional
        Optional metrics configuration (default: None). When None, uses default
        MetricsConfig() with enabled=True. Used to configure metrics collection
        and registry settings. When config.enabled is False, returns None.

    Returns
    -------
    APIRouter | None
        Router exposing `/metrics` endpoint for Prometheus scraping, or ``None``
        when FastAPI/prometheus components are unavailable or metrics are disabled.
        The router can be mounted on a FastAPI application to expose metrics.
    """
    if RuntimeAPIRouter is None or RuntimeResponse is None:
        return None
    router_cls = cast("type[APIRouter]", RuntimeAPIRouter)
    response_cls = cast("type[Response]", RuntimeResponse)
    cfg = config or MetricsConfig()
    if not cfg.enabled:
        return None
    registry_obj = cfg.registry or get_default_registry()
    if registry_obj is None:
        return None
    registry = cast("CollectorRegistry", registry_obj)
    router = router_cls()

    @router.get("/metrics")
    def metrics_endpoint() -> Response:
        """Handle GET requests to the /metrics endpoint.

        This endpoint serves Prometheus metrics in OpenMetrics format. It
        generates the metrics payload from the configured registry and returns
        it as a text/plain response with the appropriate content type.

        Returns
        -------
        Response
            FastAPI Response containing OpenMetrics-formatted metrics payload.
            The response has Content-Type set to CONTENT_TYPE_LATEST (typically
            "text/plain; version=0.0.4") and contains all metrics registered
            in the configured Prometheus registry.

        Notes
        -----
        This endpoint is designed to be scraped by Prometheus servers or other
        metrics collection systems. The metrics payload includes all counters,
        histograms, and gauges registered in the application's metrics registry.
        """
        return response_cls(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    return router


def record_run(tool: str, status: str) -> None:
    """Increment the runs counter for the given tool/status."""
    RUNS_TOTAL.labels(tool=tool, status=status).inc()


def record_run_error(tool: str, error_code: str) -> None:
    """Increment the run error counter."""
    RUN_ERRORS_TOTAL.labels(tool=tool, error_code=error_code).inc()


def observe_request_latency(tool: str, duration_s: float, status: str) -> None:
    """Record request latency for a tool/status pair."""
    REQUEST_LATENCY_SECONDS.labels(tool=tool, status=status).observe(duration_s)


def record_stage_latency(stage: str, duration_s: float) -> None:
    """Record a telemetry stage duration."""
    STAGE_LATENCY_SECONDS.labels(stage=stage).observe(duration_s)
