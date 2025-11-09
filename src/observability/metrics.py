"""Prometheus metrics shared across observability surfaces.

The counters and histograms defined here are thin wrappers around the shared
typed Prometheus helpers in :mod:`kgfoundry_common.prometheus`. They degrade to
no-op implementations automatically when Prometheus is not installed, keeping
the rest of the codebase free from conditional imports.

Examples
--------
>>> from observability.metrics import bm25_queries_total
>>> bm25_queries_total.inc()
>>> from observability.metrics import faiss_search_latency_ms
>>> faiss_search_latency_ms.observe(12.5)
"""

# [nav:section public-api]

from __future__ import annotations

from typing import TYPE_CHECKING

from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.prometheus import build_counter, build_histogram

if TYPE_CHECKING:
    from kgfoundry_common.prometheus import CounterLike, HistogramLike

__all__ = [
    "bm25_queries_total",
    "faiss_search_latency_ms",
    "pdf_download_failure_total",
    "pdf_download_success_total",
    "search_total_latency_ms",
    "splade_queries_total",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# [nav:anchor pdf_download_success_total]
pdf_download_success_total: CounterLike = build_counter(
    "pdf_download_success_total",
    "Successful OA PDF downloads",
)

# [nav:anchor pdf_download_failure_total]
pdf_download_failure_total: CounterLike = build_counter(
    "pdf_download_failure_total",
    "Failed OA PDF downloads",
    ("reason",),
)

# [nav:anchor search_total_latency_ms]
search_total_latency_ms: HistogramLike = build_histogram(
    "search_total_latency_ms",
    "End-to-end /search latency (ms)",
)

# [nav:anchor faiss_search_latency_ms]
faiss_search_latency_ms: HistogramLike = build_histogram(
    "faiss_search_latency_ms",
    "FAISS search latency (ms)",
)

# [nav:anchor bm25_queries_total]
bm25_queries_total: CounterLike = build_counter(
    "bm25_queries_total",
    "BM25 queries issued",
)

# [nav:anchor splade_queries_total]
splade_queries_total: CounterLike = build_counter(
    "splade_queries_total",
    "SPLADE queries issued",
)
