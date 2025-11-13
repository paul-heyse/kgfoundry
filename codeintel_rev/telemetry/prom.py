"""Prometheus helpers for MCP diagnostics."""

from __future__ import annotations

import os
from dataclasses import dataclass

try:  # pragma: no cover - optional dependency
    from fastapi import APIRouter
    from fastapi.responses import Response
except ModuleNotFoundError:  # pragma: no cover - fallback for tests
    APIRouter = None  # type: ignore[assignment]
    Response = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
except ImportError:  # pragma: no cover - fallback when prometheus missing
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"

    def generate_latest(_registry: object) -> bytes:
        """Return placeholder metrics when prometheus_client is unavailable.

        Returns
        -------
        bytes
            Text exposition explaining that metrics are disabled.
        """
        return b"# Prometheus metrics unavailable (prometheus_client not installed)\n"


from kgfoundry_common.prometheus import (
    CollectorRegistry,
    build_counter,
    build_histogram,
    get_default_registry,
)

__all__ = [
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


@dataclass(slots=True, frozen=True)
class MetricsConfig:
    """Configuration container for exposing `/metrics`."""

    enabled: bool = _env_flag("PROMETHEUS_ENABLED", default=True)
    registry: CollectorRegistry | None = None


def build_metrics_router(config: MetricsConfig | None = None) -> APIRouter | None:
    """Return an APIRouter exposing the Prometheus scrape endpoint.

    Returns
    -------
    APIRouter | None
        Router when FastAPI/prometheus-client are available, otherwise ``None``.
    """
    if APIRouter is None or Response is None:
        return None
    cfg = config or MetricsConfig()
    if not cfg.enabled:
        return None
    registry = cfg.registry or get_default_registry()
    if registry is None:
        return None
    router = APIRouter()

    @router.get("/metrics")
    def metrics_endpoint() -> Response:
        return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

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
