"""Prometheus metrics for hybrid retrieval."""

from __future__ import annotations

from collections.abc import Iterable

from kgfoundry_common.prometheus import (
    build_counter,
    build_gauge,
    build_histogram,
)

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
