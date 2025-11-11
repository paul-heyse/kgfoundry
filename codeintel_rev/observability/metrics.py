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
    "QUERIES_TOTAL",
    "QUERY_AMBIGUITY",
    "QUERY_ERRORS_TOTAL",
    "RECENCY_BOOSTED_TOTAL",
    "RESULTS_TOTAL",
    "RRF_DURATION_SECONDS",
    "RRF_K",
    "observe_budget_depths",
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
    ("channel",),
    unit="seconds",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0),
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


def observe_budget_depths(depths: Iterable[tuple[str, int]]) -> None:
    """Record per-channel depth decisions."""
    for channel, depth in depths:
        BUDGET_DEPTH.labels(channel=channel).set(float(depth))
