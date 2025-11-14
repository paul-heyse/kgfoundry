"""Central Prometheus metric registry for FAISS/hybrid retrieval."""

from __future__ import annotations

from kgfoundry_common.prometheus import build_counter, build_gauge, build_histogram

FAISS_BUILD_TOTAL = build_counter("faiss_build_total", "Number of FAISS index builds.")
FAISS_BUILD_SECONDS_LAST = build_gauge(
    "faiss_build_seconds_last", "Duration in seconds of the last FAISS build."
)
FAISS_INDEX_SIZE_VECTORS = build_gauge(
    "faiss_index_size_vectors", "Number of vectors stored in the FAISS index."
)
FAISS_INDEX_CODE_SIZE_BYTES = build_gauge(
    "faiss_index_code_size_bytes", "Approximate memory footprint of the FAISS index in bytes."
)
FAISS_INDEX_DIM = build_gauge(
    "faiss_index_dim", "Dimensionality of vectors stored in the FAISS index."
)
FAISS_INDEX_FACTORY = build_gauge(
    "faiss_index_factory_id", "Stable hash of the active FAISS factory string."
)
FAISS_INDEX_GPU_ENABLED = build_gauge(
    "faiss_index_gpu_enabled", "Whether the FAISS GPU clone is active (1) or not (0)."
)
FAISS_INDEX_CUVS_ENABLED = build_gauge(
    "faiss_index_cuvs_enabled",
    "Whether cuVS/CAGRA acceleration is enabled for the current index.",
)
FAISS_SEARCH_TOTAL = build_counter("faiss_search_total", "Total FAISS search invocations.")
FAISS_SEARCH_ERRORS_TOTAL = build_counter(
    "faiss_search_errors_total", "Total FAISS searches that failed."
)
FAISS_SEARCH_LAST_MS = build_gauge(
    "faiss_search_last_ms", "Latency of the most recent FAISS search."
)
FAISS_SEARCH_LAST_K = build_gauge("faiss_search_last_k", "k used by the last FAISS search.")
FAISS_SEARCH_NPROBE = build_gauge(
    "faiss_search_nprobe", "IVF nprobe value used for the most recent FAISS search."
)
_METRIC_LABELS = ("index_family", "nprobe", "ef_search", "refine_k_factor")
FAISS_ANN_LATENCY_SECONDS = build_histogram(
    "faiss_ann_latency_seconds",
    "Latency for ANN (approximate) FAISS searches.",
    labelnames=_METRIC_LABELS,
)
FAISS_REFINE_LATENCY_SECONDS = build_histogram(
    "faiss_refine_latency_seconds",
    "Latency for exact rerank refinement over hydrated embeddings.",
    labelnames=_METRIC_LABELS,
)
FAISS_POSTFILTER_DENSITY = build_gauge(
    "faiss_postfilter_density",
    "Ratio of final top-k to ANN candidate fan-out.",
    labelnames=_METRIC_LABELS,
)
FAISS_REFINE_KEPT_RATIO = build_histogram(
    "faiss_refine_kept_ratio",
    "Ratio of requested top-k to ANN candidate fan-out (measures overfetch).",
)
HNSW_SEARCH_EF = build_gauge(
    "hnsw_search_ef", "efSearch value applied during the most recent HNSW search."
)
HYBRID_RETRIEVE_TOTAL = build_counter(
    "hybrid_retrieve_total", "Hybrid retrieval orchestrations performed."
)
HYBRID_LAST_MS = build_gauge(
    "hybrid_last_ms", "Latency of the last hybrid retrieval orchestration."
)
RERANK_XTR_LAST_MS = build_gauge(
    "rerank_xtr_last_ms", "Latency of the last XTR rerank evaluation (oracle)."
)
RECALL_EST_AT_K = build_gauge(
    "recall_est_at_k", "Online estimate of recall@k produced by hybrid pooling."
)
HITS_ABOVE_THRESH = build_gauge(
    "hits_above_thresh", "Count of hybrid hits above the configured similarity threshold."
)
POOL_SHARE_FAISS = build_gauge(
    "pool_share_faiss", "Share of hybrid pool populated by FAISS/semantic hits."
)
POOL_SHARE_BM25 = build_gauge("pool_share_bm25", "Share of hybrid pool populated by BM25 hits.")
POOL_SHARE_SPLADE = build_gauge(
    "pool_share_splade", "Share of hybrid pool populated by SPLADE hits."
)
POOL_SHARE_XTR = build_gauge(
    "pool_share_xtr", "Share of hybrid pool populated by XTR/reranked hits."
)
GPU_AVAILABLE = build_gauge("faiss_gpu_available", "Whether at least one GPU is visible (1/0).")
GPU_TEMP_SCRATCH_BYTES = build_gauge(
    "faiss_gpu_temp_scratch_bytes", "Temporary scratch memory reserved for GPU FAISS resources."
)
FAISS_COMPILE_FLAGS_ID = build_gauge(
    "faiss_compile_flags_id", "Stable hash of the FAISS compile options string."
)
OFFLINE_EVAL_RECALL_AT_K = build_gauge(
    "offline_eval_recall_at_k",
    "Latest offline recall measurement",
    labelnames=("k",),
)
OFFLINE_EVAL_QUERY_COUNT = build_gauge(
    "offline_eval_query_count", "Number of queries processed in the most recent offline evaluation."
)
SCIP_CHUNK_COVERAGE_RATIO = build_gauge(
    "scip_function_chunk_coverage_ratio",
    "Fraction of SCIP function defs mapped to chunks.",
)
SCIP_INDEX_COVERAGE_RATIO = build_gauge(
    "scip_function_index_coverage_ratio",
    "Fraction of SCIP function defs with embeddings present in the chunk store.",
)
SCIP_RETRIEVAL_COVERAGE_RATIO = build_gauge(
    "scip_function_retrieval_coverage_ratio",
    "Fraction of SCIP function defs retrieved by FAISS at top-K.",
    labelnames=("k",),
)
MCP_SEARCH_LATENCY_SECONDS = build_histogram(
    "mcp_search_latency_seconds",
    "End-to-end latency for MCP Deep-Research search requests.",
)
MCP_FETCH_LATENCY_SECONDS = build_histogram(
    "mcp_fetch_latency_seconds",
    "Latency for chunk hydration performed by the MCP fetch tool.",
)
MCP_SEARCH_POSTFILTER_DENSITY = build_histogram(
    "mcp_search_postfilter_density",
    "Ratio of retained search results after filters to FAISS hits.",
)
MCP_SEARCH_ANN_LATENCY_MS = build_histogram(
    "mcp_search_ann_latency_ms", "Latency of FAISS ANN queries executed via MCP search."
)
MCP_SEARCH_HYDRATION_LATENCY_MS = build_histogram(
    "mcp_search_hydration_latency_ms",
    "Latency of DuckDB hydration performed during MCP search.",
)
MCP_SEARCH_RERANK_LATENCY_MS = build_histogram(
    "mcp_search_rerank_latency_ms",
    "Latency of the rerank/exact scoring stage during MCP search.",
)


def _stable_u32(value: str) -> int:
    """Return a deterministic 32-bit hash for the provided string.

    Extended Summary
    ----------------
    This helper computes a stable 32-bit hash using FNV-1a algorithm. The hash is
    deterministic (same input produces same output) and is used for generating
    stable metric label values. Used internally by the metrics registry to create
    consistent label identifiers.

    Parameters
    ----------
    value : str
        String to hash. The string is UTF-8 encoded before hashing.

    Returns
    -------
    int
        Unsigned 32-bit hash of ``value``. The hash is deterministic and stable
        across Python invocations for the same input string.

    Notes
    -----
    This function implements FNV-1a hash algorithm (32-bit variant). The hash is
    used for generating stable metric label values. Time complexity: O(n) where
    n is the length of the input string.
    """
    h = 2166136261
    for byte in value.encode("utf-8"):
        h ^= byte
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def set_factory_id(factory_str: str) -> None:
    """Record the current FAISS factory string as a hashed gauge."""
    FAISS_INDEX_FACTORY.set(_stable_u32(factory_str))


def set_compile_flags_id(flags: str) -> None:
    """Record FAISS compile options for readiness/diagnostics."""
    FAISS_COMPILE_FLAGS_ID.set(_stable_u32(flags))


__all__ = [
    "FAISS_ANN_LATENCY_SECONDS",
    "FAISS_BUILD_SECONDS_LAST",
    "FAISS_BUILD_TOTAL",
    "FAISS_COMPILE_FLAGS_ID",
    "FAISS_INDEX_CODE_SIZE_BYTES",
    "FAISS_INDEX_CUVS_ENABLED",
    "FAISS_INDEX_DIM",
    "FAISS_INDEX_FACTORY",
    "FAISS_INDEX_GPU_ENABLED",
    "FAISS_INDEX_SIZE_VECTORS",
    "FAISS_POSTFILTER_DENSITY",
    "FAISS_REFINE_KEPT_RATIO",
    "FAISS_REFINE_LATENCY_SECONDS",
    "FAISS_SEARCH_ERRORS_TOTAL",
    "FAISS_SEARCH_LAST_K",
    "FAISS_SEARCH_LAST_MS",
    "FAISS_SEARCH_NPROBE",
    "FAISS_SEARCH_TOTAL",
    "GPU_AVAILABLE",
    "GPU_TEMP_SCRATCH_BYTES",
    "HITS_ABOVE_THRESH",
    "HNSW_SEARCH_EF",
    "HYBRID_LAST_MS",
    "HYBRID_RETRIEVE_TOTAL",
    "MCP_FETCH_LATENCY_SECONDS",
    "MCP_SEARCH_ANN_LATENCY_MS",
    "MCP_SEARCH_HYDRATION_LATENCY_MS",
    "MCP_SEARCH_LATENCY_SECONDS",
    "MCP_SEARCH_POSTFILTER_DENSITY",
    "MCP_SEARCH_RERANK_LATENCY_MS",
    "OFFLINE_EVAL_QUERY_COUNT",
    "OFFLINE_EVAL_RECALL_AT_K",
    "POOL_SHARE_BM25",
    "POOL_SHARE_FAISS",
    "POOL_SHARE_SPLADE",
    "POOL_SHARE_XTR",
    "RECALL_EST_AT_K",
    "RERANK_XTR_LAST_MS",
    "SCIP_CHUNK_COVERAGE_RATIO",
    "SCIP_INDEX_COVERAGE_RATIO",
    "SCIP_RETRIEVAL_COVERAGE_RATIO",
    "set_compile_flags_id",
    "set_factory_id",
]
