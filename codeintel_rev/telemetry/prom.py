"""Prometheus helpers for MCP diagnostics."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from codeintel_rev.telemetry.otel_metrics import build_counter, build_histogram

if TYPE_CHECKING:  # pragma: no cover
    from fastapi import APIRouter
    from fastapi.responses import Response

    ResponseType = Response
else:
    ResponseType = Any

try:  # pragma: no cover - optional dependency
    from fastapi import APIRouter as RuntimeAPIRouter
    from fastapi.responses import Response as RuntimeResponse
except ModuleNotFoundError:  # pragma: no cover - fallback for tests
    RuntimeAPIRouter = None
    RuntimeResponse = None


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


def build_metrics_router(config: MetricsConfig | None = None) -> APIRouter | None:
    """Return an APIRouter exposing a compatibility message.

    The OpenTelemetry Prometheus reader now serves metrics directly. This
    router informs operators where to scrape metrics instead of proxying
    prometheus_client output from the application process.

    Parameters
    ----------
    config : MetricsConfig | None
        Optional metrics configuration. If None, uses default configuration
        from environment variables. Defaults to None.

    Returns
    -------
    APIRouter | None
        Router exposing `/metrics` or ``None`` when FastAPI is unavailable
        or metrics are disabled.
    """
    if RuntimeAPIRouter is None or RuntimeResponse is None:
        return None
    router_cls = RuntimeAPIRouter
    response_cls = RuntimeResponse
    cfg = config or MetricsConfig()
    if not cfg.enabled:
        return None
    router = router_cls()  # type: ignore[call-arg]

    @router.get("/metrics")
    def metrics_endpoint() -> ResponseType:  # type: ignore[override]
        """Return a compatibility message directing operators to the OpenTelemetry reader.

        This endpoint returns HTTP 410 (Gone) with a message informing operators
        that metrics have moved to the OpenTelemetry Prometheus reader. It is
        maintained for backward compatibility to prevent confusion when operators
        attempt to scrape the legacy `/metrics` endpoint.

        Returns
        -------
        ResponseType
            Plain text response with HTTP 410 status code and redirect message.
        """
        message = (
            "Metrics have moved to the OpenTelemetry Prometheus reader. "
            "Scrape the reader port (default :9464) instead of /metrics."
        )
        return response_cls(content=message, media_type="text/plain", status_code=410)

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
