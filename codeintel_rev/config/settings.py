"""Configuration settings using msgspec for fast, validated config.

NO Pydantic - using msgspec.Struct for performance-critical settings.
All configuration loaded from environment variables with sensible defaults.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import msgspec

from codeintel_rev.io.duckdb_manager import DuckDBConfig

DEFAULT_RRF_WEIGHTS: dict[str, float] = {
    "semantic": 1.0,
    "bm25": 1.0,
    "splade": 1.0,
    "warp": 1.1,
}


@dataclass(frozen=True)
class _HybridChannelSettings:
    bm25_enabled: bool
    splade_enabled: bool
    bm25_k1: float
    bm25_b: float


def _env_bool(key: str, *, default: bool = False) -> bool:
    """Return a boolean flag parsed from environment variables.

    Parameters
    ----------
    key : str
        Environment variable name to read.
    default : bool, optional
        Default value if the environment variable is not set. Defaults to False.

    Returns
    -------
    bool
        Boolean value parsed from the environment variable. Returns True if the
        value is "1", "true", or "yes" (case-insensitive), False otherwise.
    """
    default_str = "1" if default else "0"
    return os.environ.get(key, default_str).strip().lower() in {"1", "true", "yes"}


def _parse_int_with_suffix(value: str, default: int) -> int:
    """Return an integer, accepting 1k-style suffixes (k=1_000).

    Extended Summary
    ----------------
    This helper parses integer values from configuration strings, supporting
    compact notation with 'k' suffix (e.g., "10k" = 10000). Used for parsing
    environment variables that specify sizes or counts in a human-readable format.
    Normalizes input by stripping whitespace, converting to lowercase, and removing
    underscores before parsing.

    Parameters
    ----------
    value : str
        String to parse, optionally ending with 'k' suffix (e.g., "10k", "1_000k").
        Whitespace and underscores are normalized before parsing.
    default : int
        Default value returned if parsing fails, value is empty, or ValueError
        is raised during conversion.

    Returns
    -------
    int
        Parsed integer value, or default if parsing fails or value is empty.
        Suffix 'k' multiplies the numeric part by 1000.

    Notes
    -----
    This helper is used for parsing configuration values that may be specified
    in compact notation (e.g., "10k" instead of "10000"). Defensively handles
    malformed input by returning the default value. Time complexity: O(n) where
    n is the length of the input string.
    """
    normalized = value.strip().lower().replace("_", "")
    if not normalized:
        return default
    try:
        if normalized.endswith("k"):
            return int(float(normalized[:-1]) * 1000)
        return int(normalized)
    except ValueError:
        return default


def _parse_int_list(env_value: str | None, fallback: tuple[int, ...]) -> tuple[int, ...]:
    """Return a tuple of integers from a comma-separated configuration string.

    Extended Summary
    ----------------
    This helper parses comma-separated integer lists from configuration strings
    (e.g., "10,20,30" -> (10, 20, 30)). Used for parsing environment variables
    that specify multiple integer values. If any element fails to parse, the
    entire operation fails and returns the fallback value.

    Parameters
    ----------
    env_value : str | None
        Comma-separated string of integers (e.g., "10,20,30"). Whitespace around
        commas is stripped. If None or empty, returns fallback.
    fallback : tuple[int, ...]
        Default value returned if parsing fails, env_value is None/empty, or
        any element cannot be converted to int.

    Returns
    -------
    tuple[int, ...]
        Parsed integers, or fallback if parsing fails or env_value is None/empty.
        Empty strings between commas are ignored.

    Notes
    -----
    This helper is used for parsing configuration values that specify multiple
    integers (e.g., nlist values for adaptive indexing). Defensively handles
    malformed input by returning the fallback value. Time complexity: O(n) where
    n is the length of the input string.
    """
    if not env_value:
        return fallback
    parts = [part.strip() for part in env_value.split(",")]
    parsed: list[int] = []
    for part in parts:
        if not part:
            continue
        try:
            parsed.append(int(part))
        except ValueError:
            return fallback
    return tuple(parsed) if parsed else fallback


def _optional_int(raw: str | None) -> int | None:
    """Convert an optional string to ``int`` when possible.

    Extended Summary
    ----------------
    This helper safely converts optional configuration strings to integers.
    Used for parsing environment variables that may be unset or empty. Returns
    None for None, empty strings, or invalid values, allowing callers to use
    None as a sentinel for "not configured".

    Parameters
    ----------
    raw : str | None
        String to convert to integer. If None, empty, or contains non-numeric
        characters (after stripping), returns None.

    Returns
    -------
    int | None
        Parsed integer, or None if raw is None, empty, or invalid. ValueError
        during conversion is caught and returns None.

    Notes
    -----
    This helper is used for parsing optional configuration values where None
    indicates "use default" rather than "zero". Defensively handles malformed
    input by returning None. Time complexity: O(1) for None/empty, O(n) for
    parsing where n is the string length.
    """
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _build_vllm_config() -> VLLMConfig:
    run_mode_env = os.environ.get("VLLM_RUN_MODE", "inprocess").lower()
    run_mode = VLLMRunMode(mode="http" if run_mode_env == "http" else "inprocess")
    pooling_env = os.environ.get("VLLM_POOLING_TYPE", "lasttoken").lower()
    if pooling_env == "cls":
        pooling_type: Literal["lasttoken", "cls", "mean"] = "cls"
    elif pooling_env == "mean":
        pooling_type = "mean"
    else:
        pooling_type = "lasttoken"
    return VLLMConfig(
        base_url=os.environ.get("VLLM_URL", "http://127.0.0.1:8001/v1"),
        model=os.environ.get("VLLM_MODEL", "nomic-ai/nomic-embed-code"),
        batch_size=int(os.environ.get("VLLM_BATCH_SIZE", "64")),
        embedding_dim=int(os.environ.get("VLLM_EMBED_DIM", "2560")),
        timeout_s=float(os.environ.get("VLLM_TIMEOUT_S", "120.0")),
        run=run_mode,
        gpu_memory_utilization=float(os.environ.get("VLLM_GPU_MEMORY_UTILIZATION", "0.92")),
        max_num_batched_tokens=_parse_int_with_suffix(
            os.environ.get("VLLM_MAX_BATCHED_TOKENS", "65536"),
            65_536,
        ),
        normalize=os.environ.get("VLLM_NORMALIZE", "1").lower() in {"1", "true", "yes"},
        pooling_type=pooling_type,
        max_concurrent_requests=int(os.environ.get("VLLM_MAX_CONCURRENT_REQUESTS", "4")),
    )


def _build_xtr_config() -> XTRConfig:
    dtype_env = (os.environ.get("XTR_DTYPE") or "float16").lower()
    mode_env = os.environ.get("XTR_MODE", "narrow").lower()
    mode: Literal["narrow", "wide"] = "wide" if mode_env == "wide" else "narrow"
    return XTRConfig(
        model_id=os.environ.get("XTR_MODEL_ID", "nomic-ai/CodeRankEmbed"),
        device=os.environ.get("XTR_DEVICE", "cuda"),
        max_query_tokens=int(os.environ.get("XTR_MAX_QUERY_TOKENS", "256")),
        candidate_k=int(os.environ.get("XTR_CANDIDATE_K", "200")),
        dim=int(os.environ.get("XTR_DIM", "768")),
        dtype="float32" if dtype_env == "float32" else "float16",
        enable=os.environ.get("XTR_ENABLE", "0").lower() in {"1", "true", "yes"},
        mode=mode,
    )


def _build_rerank_config() -> RerankConfig:
    provider = os.environ.get("RERANK_PROVIDER", "xtr").lower()
    provider_literal: Literal["xtr"] = "xtr"
    return RerankConfig(
        enabled=os.environ.get("RERANK_ENABLED", "0").lower() in {"1", "true", "yes"},
        top_k=int(os.environ.get("RERANK_TOP_K", "50")),
        provider=provider_literal if provider == "xtr" else "xtr",
        explain=os.environ.get("RERANK_EXPLAIN", "0").lower() in {"1", "true", "yes"},
    )


class CodeRankConfig(msgspec.Struct, frozen=True):
    """Configuration for the CodeRank dense retriever.

    Attributes
    ----------
    model_id : str
        Hugging Face model identifier for CodeRank embeddings (bi-encoder).
    trust_remote_code : bool
        Whether to allow custom modules provided by the model repository.
    device : str
        Device identifier ("cpu", "cuda", or "auto") used for inference.
    batch_size : int
        Batch size used while encoding queries or code chunks.
    normalize : bool
        When ``True`` (default), normalize embeddings for cosine similarity.
    query_prefix : str
        Instruction prefix required by the CodeRank model card for queries.
    top_k : int
        Maximum number of candidates to retrieve during Stage-A.
    budget_ms : int
        Soft latency budget for CodeRank embedding + ANN search.
    min_stage2_margin : float
        Score margin threshold that skips Stage-B when confidence is high.
    min_stage2_candidates : int
        Minimum candidate count required to invoke Stage-B.
    """

    model_id: str = "nomic-ai/CodeRankEmbed"
    trust_remote_code: bool = True
    device: str = "cpu"
    batch_size: int = 128
    normalize: bool = True
    query_prefix: str = "Represent this query for searching relevant code: "
    top_k: int = 200
    budget_ms: int = 120
    min_stage2_margin: float = 0.1
    min_stage2_candidates: int = 40


class WarpConfig(msgspec.Struct, frozen=True):
    """Configuration for the WARP/XTR late-interaction reranker.

    Attributes
    ----------
    index_dir : str
        Directory containing the compiled WARP/XTR index artifacts.
    model_id : str
        Identifier for the multivector encoder used by WARP (for reference).
    device : str
        Target device for the WARP executor ("cpu" or "cuda").
    top_k : int
        Candidate fan-out requested from the WARP executor.
    enabled : bool
        Gate to enable/disable WARP at runtime (defaults to ``False``).
    budget_ms : int
        Soft latency budget for the WARP reranking stage.
    """

    index_dir: str = "indexes/warp_xtr"
    model_id: str = "intfloat/e5-multivector-large"
    device: str = "cpu"
    top_k: int = 200
    enabled: bool = False
    budget_ms: int = 180


class XTRConfig(msgspec.Struct, frozen=True):
    """Configuration for XTR token storage and scoring."""

    model_id: str = "nomic-ai/CodeRankEmbed"
    device: str = "cuda"
    max_query_tokens: int = 256
    candidate_k: int = 200
    dim: int = 768
    dtype: Literal["float16", "float32"] = "float16"
    enable: bool = False
    mode: Literal["narrow", "wide"] = "narrow"


class RerankConfig(msgspec.Struct, frozen=True):
    """Configuration for optional late-interaction reranking."""

    enabled: bool = False
    top_k: int = 50
    provider: Literal["xtr"] = "xtr"
    explain: bool = False


class EvalConfig(msgspec.Struct, frozen=True):
    """Offline evaluation configuration."""

    enabled: bool = False
    queries_path: str | None = None
    output_dir: str = "artifacts/eval"
    k_values: tuple[int, ...] = (5, 10, 20)
    max_queries: int | None = 200
    oracle_top_k: int = 50
    xtr_as_oracle: bool = False


class CodeRankLLMConfig(msgspec.Struct, frozen=True):
    """Configuration for the CodeRank listwise reranker."""

    model_id: str = "nomic-ai/CodeRankLLM"
    device: str = "cpu"
    max_new_tokens: int = 256
    temperature: float = 0.0
    top_p: float = 1.0
    enabled: bool = False
    budget_ms: int = 300


class VLLMRunMode(msgspec.Struct, frozen=True):
    """Execution mode for the vLLM embedder."""

    mode: Literal["inprocess", "http"] = "inprocess"


class VLLMConfig(msgspec.Struct, frozen=True):
    """vLLM embedding service configuration.

    Configuration for connecting to a vLLM embedding service that provides
    OpenAI-compatible embeddings API. This is used for generating vector embeddings
    of code chunks during indexing and for query embeddings during semantic search.

    The vLLM service runs separately (typically on a GPU-enabled machine) and
    provides fast batch embedding generation. The configuration includes connection
    details, model selection, and performance tuning parameters.

    Attributes
    ----------
    base_url : str
        Base URL for the vLLM embeddings API endpoint. Should point to the /v1
        endpoint of a running vLLM server. Defaults to localhost:8001.
    model : str
        Model identifier for embeddings. This should match a model that the
        vLLM server has loaded. Defaults to "nomic-ai/nomic-embed-code" which
        is a code-specific embedding model with 2560 dimensions.
    batch_size : int
        Number of texts to embed in a single batch request. Larger batches improve
        throughput but increase memory usage. Defaults to 64, which is a good
        balance for most GPU setups.
    embedding_dim : int
        Dimensionality of embeddings returned by the configured model. Defaults to
        2560 to match the deployed nomic-embed-code checkpoint. Consumers should
        keep this aligned with :class:`IndexConfig` ``vec_dim``.
    timeout_s : float
        HTTP request timeout in seconds. Embedding requests can take time for
        large batches, so this should be set appropriately. Defaults to 120 seconds.
    run : VLLMRunMode
        Runtime execution mode for vLLM. Controls whether embeddings are generated
        via HTTP requests to a remote service ("http") or using an in-process vLLM
        engine ("inprocess"). Defaults to "inprocess" for local development.
    gpu_memory_utilization : float
        Fraction of GPU memory to allocate for vLLM model and KV cache. Range [0.0, 1.0].
        Higher values improve throughput but reduce available memory for other operations.
        Defaults to 0.92 (92% of GPU memory).
    max_num_batched_tokens : int
        Maximum number of tokens to process in a single batch. Larger values improve
        throughput but increase memory usage and latency. Defaults to 65536 tokens.
    normalize : bool
        Whether to L2-normalize embeddings after generation. Normalized embeddings
        enable cosine similarity computation via dot product. Defaults to True.
    pooling_type : Literal["lasttoken", "cls", "mean"]
        Token pooling strategy for generating embeddings from token-level outputs.
        "lasttoken" uses the final token embedding, "cls" uses a special CLS token,
        "mean" averages all token embeddings. Defaults to "lasttoken".
    max_concurrent_requests : int
        Maximum number of concurrent embedding requests allowed when using HTTP mode.
        Higher values improve throughput but increase memory usage. Defaults to 4.
    """

    base_url: str = "http://127.0.0.1:8001/v1"
    model: str = "nomic-ai/nomic-embed-code"
    batch_size: int = 64
    embedding_dim: int = 2560
    timeout_s: float = 120.0
    run: VLLMRunMode = VLLMRunMode()
    gpu_memory_utilization: float = 0.92
    max_num_batched_tokens: int = 65_536
    normalize: bool = True
    pooling_type: Literal["lasttoken", "cls", "mean"] = "lasttoken"
    max_concurrent_requests: int = 4


class BM25Config(msgspec.Struct, frozen=True):
    """BM25 indexing and search configuration."""

    corpus_json_dir: str = "data/jsonl"
    index_dir: str = "indexes/bm25"
    threads: int = 8
    enabled: bool = True
    k1: float = 0.9
    b: float = 0.4
    rm3_enabled: bool = False
    rm3_fb_docs: int = 10
    rm3_fb_terms: int = 10
    rm3_original_query_weight: float = 0.5
    analyzer: Literal["code", "standard"] = "code"
    stopwords: tuple[str, ...] = ()


class PRFConfig(msgspec.Struct, frozen=True):
    """Pseudo relevance feedback (RM3) configuration."""

    enable_auto: bool = True
    fb_docs: int = 10
    fb_terms: int = 10
    orig_weight: float = 0.5
    short_query_max_terms: int = 3
    symbol_like_regex: str | None = None
    head_terms_csv: str | None = None


class SpladeConfig(msgspec.Struct, frozen=True):
    """SPLADE v3 configuration covering model artifacts and index directories.

    Attributes
    ----------
    model_id : str
        Hugging Face model identifier used for training or export. Defaults to
        ``naver/splade-v3``.
    model_dir : str
        Local directory that stores exported model artifacts. Defaults to
        ``models/splade-v3``.
    onnx_dir : str
        Directory containing exported ONNX models. Defaults to ``models/splade-v3/onnx``.
    onnx_file : str
        Primary ONNX file name (relative to ``onnx_dir``). Defaults to ``model_qint8.onnx``.
    vectors_dir : str
        Directory that stores SPLADE JsonVectorCollection shards. Defaults to
        ``data/splade_vectors``.
    index_dir : str
        Output directory for the Lucene impact index. Defaults to ``indexes/splade_v3_impact``.
    provider : str
        Default ONNX Runtime execution provider. Defaults to ``CPUExecutionProvider``.
    quantization : int
        Integer quantization factor applied during encoding. Defaults to ``100``.
    max_terms : int
        Maximum number of query terms to retain when expanding SPLADE queries. Defaults to ``3000``.
    max_clause_count : int
        Lucene Boolean clause limit applied during indexing. Defaults to ``4096``.
    batch_size : int
        Default encoding batch size for CLI utilities. Defaults to ``32``.
    threads : int
        Default thread count used for Lucene impact index builds. Defaults to ``8``.
    enabled : bool
        Whether the SPLADE channel is enabled. Defaults to ``True``. When disabled,
        the SPLADE channel is skipped during hybrid search.
    max_query_terms : int
        Maximum number of query terms to retain when expanding SPLADE queries.
        Defaults to ``64``.
    prune_below : float
        Minimum score threshold for pruning query terms. Terms with scores below
        this threshold are excluded. Defaults to ``0.0`` (no pruning).
    analyzer : Literal["wordpiece", "code"]
        Tokenizer analyzer type. "wordpiece" uses standard WordPiece tokenization,
        "code" uses code-aware tokenization. Defaults to ``"wordpiece"``.
    static_prune_pct : float
        Static pruning percentage applied during query expansion. Defaults to ``0.0``
        (no static pruning).
    """

    model_id: str = "naver/splade-v3"
    model_dir: str = "models/splade-v3"
    onnx_dir: str = "models/splade-v3/onnx"
    onnx_file: str = "model_qint8.onnx"
    vectors_dir: str = "data/splade_vectors"
    index_dir: str = "indexes/splade_v3_impact"
    provider: str = "CPUExecutionProvider"
    quantization: int = 100
    max_terms: int = 3000
    max_clause_count: int = 4096
    batch_size: int = 32
    threads: int = 8
    enabled: bool = True
    max_query_terms: int = 64
    prune_below: float = 0.0
    analyzer: Literal["wordpiece", "code"] = "wordpiece"
    static_prune_pct: float = 0.0


class PathsConfig(msgspec.Struct, frozen=True):
    """File system paths configuration.

    Centralized configuration for all file system paths used by the code intelligence
    system. This includes paths for data storage, indexes, and source code locations.
    All paths can be relative (to repo_root) or absolute.

    The paths are organized hierarchically: data_dir contains subdirectories for
    different types of data (vectors, indexes, etc.). This structure makes it easy
    to manage and back up the entire index state.

    Attributes
    ----------
    repo_root : str
        Absolute path to the repository root directory. This is the base directory
        for all source code indexing and is used to resolve relative file paths
        from SCIP indexes. Required - no default.
    data_dir : str
        Base directory for all data storage (indexes, vectors, databases). Defaults
        to "data" relative to repo_root. This directory will contain subdirectories
        for vectors, FAISS indexes, Lucene indexes, etc.
    vectors_dir : str
        Directory containing Parquet files with vector embeddings. Each Parquet file
        stores chunks with their embeddings in Arrow FixedSizeList format for
        efficient zero-copy access. Defaults to "data/vectors".
    faiss_index : str
        Path to the FAISS IVF-PQ index file (CPU version). This is the persisted
        index that can be loaded and cloned to GPU. Defaults to
        "data/faiss/code.ivfpq.faiss".
    faiss_idmap_path : str
        Path to the FAISS ID map Parquet sidecar. This file stores the mapping
        from FAISS row IDs to external chunk IDs for deterministic hydration.
        Defaults to "data/faiss/faiss_idmap.parquet".
    lucene_dir : str
        Directory for Lucene/BM25 indexes. Used for sparse retrieval methods like
        BM25 keyword search. Defaults to "data/lucene".
    splade_dir : str
        Directory for SPLADE (Sparse Lexical and Dense) impact indexes. SPLADE
        provides learned sparse representations that combine benefits of keyword
        and dense search. Defaults to "data/splade".
    duckdb_path : str
        Path to the DuckDB catalog database file. DuckDB provides SQL views over
        Parquet files, enabling fast queries for chunk metadata, filtering, and
        joins. Defaults to "data/catalog.duckdb".
    scip_index : str
        Path to the SCIP index file (either protobuf .scip or JSON .scip.json).
        This is the source of truth for symbol definitions and is generated by
        the SCIP Python indexer. Defaults to "index.scip" in repo_root.
    coderank_vectors_dir : str
        Directory that stores CodeRank chunk embeddings (parquet or npy shards).
    coderank_faiss_index : str
        Path to the CodeRank FAISS index file used for Stage-A retrieval.
    warp_index_dir : str
        Directory containing WARP/XTR index artifacts.
    xtr_dir : str
        Directory containing XTR token-level artifacts (memmaps + metadata).
    """

    repo_root: str
    data_dir: str = "data"
    vectors_dir: str = "data/vectors"
    faiss_index: str = "data/faiss/code.ivfpq.faiss"
    faiss_idmap_path: str = "data/faiss/faiss_idmap.parquet"
    lucene_dir: str = "data/lucene"
    splade_dir: str = "data/splade"
    duckdb_path: str = "data/catalog.duckdb"
    scip_index: str = "index.scip"
    coderank_vectors_dir: str = "data/coderank_vectors"
    coderank_faiss_index: str = "data/faiss/coderank.ivfpq.faiss"
    warp_index_dir: str = "indexes/warp_xtr"
    xtr_dir: str = "data/xtr"


class IndexConfig(msgspec.Struct, frozen=True):
    """Indexing and search configuration.

    This configuration controls chunking, embedding dimensionality, FAISS build and
    search-time parameters, and the hybrid retrieval stacks (BM25, SPLADE, fusion).
    The defaults favor accuracy-first personal RAG deployments: IVF/PQ with OPQ
    pre-rotation, higher search fan-out, structured logging, and GPU/cuVS when
    available. Backwards-compatible legacy knobs (``faiss_nlist`` / ``faiss_nprobe``)
    remain but new code should prefer the richer ``faiss_family`` + runtime tuning
    controls introduced here.
    """

    vec_dim: int = 2560
    chunk_budget: int = 2200
    faiss_nlist: int = 8192
    faiss_nprobe: int = 128
    bm25_k1: float = 0.9
    bm25_b: float = 0.4
    rrf_k: int = 60
    enable_bm25_channel: bool = True
    enable_splade_channel: bool = True
    hybrid_top_k_per_channel: int = 50
    use_cuvs: bool = True
    faiss_preload: bool = False
    duckdb_materialize: bool = False
    preview_max_chars: int = 240
    compaction_threshold: float = 0.05
    rrf_weights: dict[str, float] = msgspec.field(
        default_factory=lambda: {"semantic": 1.0, "bm25": 1.0, "splade": 1.0, "warp": 1.1}
    )
    hybrid_prefetch: dict[str, int] = msgspec.field(
        default_factory=lambda: {"semantic": 200, "bm25": 200, "splade": 200}
    )
    hybrid_use_rrf: bool = True
    hybrid_weights_override: dict[str, float] = msgspec.field(default_factory=dict)
    prf: PRFConfig = PRFConfig()
    recency_enabled: bool = False
    recency_half_life_days: float = 30.0
    recency_max_boost: float = 0.15
    recency_table: str = "chunks"

    # Modern FAISS construction/runtime controls ---------------------------------
    faiss_family: Literal[
        "auto",
        "flat",
        "ivf_flat",
        "ivf_pq",
        "ivf_pq_refine",
        "hnsw",
    ] = "auto"
    nlist: int | None = None
    pq_m: int = 64
    pq_nbits: int = 8
    opq_m: int = 0
    hnsw_m: int = 32
    hnsw_ef_construction: int = 200
    default_k: int = 50
    default_nprobe: int | None = None
    hnsw_ef_search: int = 128
    refine_k_factor: float = 1.0
    use_gpu: bool = True
    gpu_clone_mode: Literal["replicate", "shard"] = "replicate"
    autotune_on_start: bool = False
    enable_range_search: bool = False
    semantic_min_score: float = 0.0

    def __post_init__(self) -> None:  # pragma: no cover - simple attribute wiring
        """Bridge legacy and new fields so existing callers continue to work."""
        resolved_nlist = self.nlist or self.faiss_nlist
        resolved_nprobe = self.default_nprobe or self.faiss_nprobe
        object.__setattr__(self, "nlist", resolved_nlist)
        object.__setattr__(self, "default_nprobe", resolved_nprobe)


class ServerLimits(msgspec.Struct, frozen=True):
    """Server resource limits and rate limiting configuration.

    Configuration for protecting the server from resource exhaustion and ensuring
    fair usage. These limits prevent individual queries from consuming excessive
    resources and provide basic rate limiting for API access.

    The defaults are conservative and suitable for production deployments. Adjust
    based on your hardware capabilities and expected load patterns.

    Attributes
    ----------
    max_results : int
        Maximum number of results to return per query. This prevents queries from
        returning excessively large result sets that could cause memory issues or
        slow response times. Defaults to 1000 results, which is typically more
        than needed for most use cases. For interactive search, 50-100 is usually
        sufficient.
    query_timeout_s : float
        Maximum time in seconds that a query is allowed to run before timing out.
        This protects against slow queries (e.g., very large FAISS searches) that
        could block the server. Defaults to 30 seconds, which should be sufficient
        for most semantic searches even on large indexes. For very large indexes
        (>10M vectors), consider increasing to 60 seconds.
    rate_limit_qps : float
        Queries per second (QPS) rate limit. This is the sustained rate at which
        queries are allowed. Defaults to 10 QPS, which is reasonable for a single
        server instance. For production deployments behind a load balancer, this
        should be set per-instance (total QPS = instances * rate_limit_qps).
    rate_limit_burst : int
        Burst capacity for the rate limiter. This allows short bursts above the
        QPS limit to handle traffic spikes. Defaults to 20 queries, which allows
        a 2-second burst at 10 QPS. Set higher (40-60) if you expect more variable
        traffic patterns.
    semantic_overfetch_multiplier : int
        Multiplier applied to FAISS search fan-out when scope filters are active.
        Defaults to 2 (fetch twice the requested limit to compensate for filtering).
    """

    max_results: int = 1000
    query_timeout_s: float = 30.0
    rate_limit_qps: float = 10.0
    rate_limit_burst: int = 20
    semantic_overfetch_multiplier: int = 2


class RedisConfig(msgspec.Struct, frozen=True):
    """Redis configuration for scope storage.

    Attributes
    ----------
    url : str
        Redis connection URL. Defaults to local Redis on standard port.
    scope_l1_size : int
        Maximum number of entries to retain in the in-process L1 cache.
    scope_l1_ttl_seconds : float
        Time-to-live in seconds for L1 cache entries.
    scope_l2_ttl_seconds : int
        Time-to-live in seconds for Redis entries (L2 cache).
    """

    url: str = "redis://127.0.0.1:6379/0"
    scope_l1_size: int = 256
    scope_l1_ttl_seconds: float = 300.0
    scope_l2_ttl_seconds: int = 3600


class Settings(msgspec.Struct, frozen=True):
    """Global settings container for the entire code intelligence system.

    This is the root configuration object that aggregates all subsystem
    configurations. It's loaded once at application startup from environment
    variables and remains immutable throughout the application lifetime.

    The Settings object is frozen (immutable) to prevent accidental modification
    and ensure thread-safe access. All configuration is validated at load time
    through msgspec's type system.

    Attributes
    ----------
    vllm : VLLMConfig
        Configuration for the vLLM embedding service. Includes connection details,
        model selection, and batching parameters for generating code embeddings.
    paths : PathsConfig
        File system path configuration. Defines where indexes, vectors, databases,
        and source code are stored. All paths are resolved relative to repo_root.
    index : IndexConfig
        Indexing and search algorithm configuration. Includes chunking parameters,
        FAISS index structure, BM25 settings, and hybrid retrieval fusion parameters.
    limits : ServerLimits
        Server resource limits and rate limiting configuration. Protects against
        resource exhaustion and provides basic API rate limiting.
    redis : RedisConfig
        Redis configuration for session scope caching.
    duckdb : DuckDBConfig
        DuckDB connection configuration (threading, object cache).
    bm25 : BM25Config
        BM25 indexing configuration, including corpus preparation directories and
        default thread settings.
    splade : SpladeConfig
        SPLADE v3 configuration covering model artifacts, ONNX execution defaults, and
        Lucene impact index locations.
    coderank : CodeRankConfig
        Dense CodeRank retriever configuration.
    warp : WarpConfig
        WARP/XTR late-interaction configuration.
    xtr : XTRConfig
        Token-level index and scoring configuration.
    rerank : RerankConfig
        Late-interaction reranker configuration.
    coderank_llm : CodeRankLLMConfig
        CodeRank listwise reranker configuration.
    eval : EvalConfig
        Offline evaluation (recall/coverage) configuration.
    """

    vllm: VLLMConfig
    paths: PathsConfig
    index: IndexConfig
    limits: ServerLimits
    redis: RedisConfig
    duckdb: DuckDBConfig
    bm25: BM25Config
    splade: SpladeConfig
    coderank: CodeRankConfig
    warp: WarpConfig
    xtr: XTRConfig
    rerank: RerankConfig
    coderank_llm: CodeRankLLMConfig
    eval: EvalConfig


def load_settings() -> Settings:
    """Load settings from environment variables with sensible defaults.

    This function reads configuration from environment variables and constructs
    a Settings object with all subsystem configurations. Environment variables
    follow a hierarchical naming scheme: subsystem name in uppercase, then
    the parameter name.

    All environment variables are optional - sensible defaults are provided for
    development and testing. For production deployments, you should set at minimum:
    REPO_ROOT, VLLM_URL, and any paths that differ from defaults.

    The function validates types (converting strings to int/float/bool as needed)
    and ensures required fields (like repo_root) have values. If REPO_ROOT is
    not set, it defaults to the current working directory.

    Returns
    -------
    Settings
        Fully configured Settings instance with all subsystems initialized.
        The Settings object is frozen (immutable) and can be safely shared across
        threads.

    See Also
    --------
    The following environment variables can be used to configure the settings:
    ---------------------
    VLLM_URL : str, optional
        vLLM service base URL (default: "http://127.0.0.1:8001/v1").
    VLLM_MODEL : str, optional
        Embedding model identifier (default: "nomic-ai/nomic-embed-code").
    VLLM_BATCH_SIZE : int, optional
        Batch size for embedding requests (default: 64).
    VLLM_TIMEOUT_S : float, optional
        HTTP timeout for vLLM requests in seconds (default: 120.0).
    VLLM_EMBED_DIM : int, optional
        Embedding vector dimension for empty responses and validation
        (default: 2560).
    REPO_ROOT : str, optional
        Repository root directory path (default: current working directory).
    DATA_DIR : str, optional
        Base data directory (default: "data").
    VECTORS_DIR : str, optional
        Vector storage directory (default: "data/vectors").
    FAISS_INDEX : str, optional
        FAISS index file path (default: "data/faiss/code.ivfpq.faiss").
    FAISS_IDMAP_PATH : str, optional
        Path to the FAISS ID map Parquet sidecar (default: "data/faiss/faiss_idmap.parquet").
    LUCENE_DIR : str, optional
        Lucene index directory (default: "data/lucene").
    SPLADE_DIR : str, optional
        SPLADE index directory (default: "data/splade").
    DUCKDB_PATH : str, optional
        DuckDB catalog database path (default: "data/catalog.duckdb").
    SCIP_INDEX : str, optional
        SCIP index file path (default: "index.scip").
    VEC_DIM : int, optional
        Embedding vector dimension (default: 2560).
    CHUNK_BUDGET : int, optional
        Target chunk size in characters (default: 2200).
    FAISS_NLIST : int, optional
        Number of IVF centroids (default: 8192).
    FAISS_NPROBE : int, optional
        Number of IVF cells to probe during search (default: 128).
    FAISS_COMPACTION_THRESHOLD : float, optional
        Secondary-to-primary ratio that triggers compaction (default: 0.05).
    BM25_K1 : float, optional
        BM25 k1 parameter (default: 0.9).
    BM25_B : float, optional
        BM25 b parameter (default: 0.4).
    RRF_K : int, optional
        RRF fusion K parameter (default: 60).
    HYBRID_ENABLE_BM25 : str, optional
        Enable BM25 channel within hybrid retrieval fusion ("1"/"true" to enable, default enabled).
    HYBRID_ENABLE_SPLADE : str, optional
        Enable SPLADE channel within hybrid retrieval fusion
        ("1"/"true" to enable, default enabled).
    HYBRID_TOP_K_PER_CHANNEL : int, optional
        Per-channel candidate fan-out gathered prior to RRF fusion (default: 50).
    USE_CUVS : str, optional
        Enable cuVS acceleration: "1", "true", or "yes" (default: "1").
    FAISS_PRELOAD : str, optional
        Pre-load FAISS index at startup: "1", "true", or "yes" (default: "0").
        When enabled, startup takes 2-10 seconds longer but first request is faster.
    MAX_RESULTS : int, optional
        Maximum results per query (default: 1000).
    QUERY_TIMEOUT_S : float, optional
        Query timeout in seconds (default: 30.0).
    RATE_LIMIT_QPS : float, optional
        Rate limit queries per second (default: 10.0).
    RATE_LIMIT_BURST : int, optional
        Rate limit burst capacity (default: 20).
    REDIS_URL : str, optional
        Redis connection URL for Session scope storage (default: "redis://127.0.0.1:6379/0").
    REDIS_SCOPE_L1_SIZE : int, optional
        Maximum number of entries for the in-process L1 cache (default: 256).
    REDIS_SCOPE_L1_TTL_SECONDS : float, optional
        TTL in seconds for L1 cache entries (default: 300).
    REDIS_SCOPE_L2_TTL_SECONDS : int, optional
        TTL in seconds for Redis entries (default: 3600).
    DUCKDB_THREADS : int, optional
        Worker thread budget for DuckDB connections (default: 4).
    DUCKDB_OBJECT_CACHE : str, optional
        Enable DuckDB object cache ("1"/"true" to enable, default enabled).
    DUCKDB_LOG_QUERIES : str, optional
        Emit DuckDB SQL statements at debug level ("1"/"true" to enable).
    BM25_JSONL_DIR : str, optional
        Directory containing BM25 JsonCollection documents (default: "data/jsonl").
    BM25_INDEX_DIR : str, optional
        Directory for the Lucene BM25 index (default: "indexes/bm25").
    BM25_THREADS : int, optional
        Worker thread budget for BM25 indexing (default: 8).
    SPLADE_MODEL_ID : str, optional
        Hugging Face model identifier for SPLADE (default: "naver/splade-v3").
    SPLADE_MODEL_DIR : str, optional
        Local directory for SPLADE model artifacts (default: "models/splade-v3").
    SPLADE_ONNX_DIR : str, optional
        Directory that stores exported SPLADE ONNX artifacts (default: "models/splade-v3/onnx").
    SPLADE_ONNX_FILE : str, optional
        Primary SPLADE ONNX file name (default: "model_qint8.onnx").
    SPLADE_VECTORS_DIR : str, optional
        Directory containing SPLADE JsonVectorCollection shards (default: "data/splade_vectors").
    SPLADE_INDEX_DIR : str, optional
        Directory for the SPLADE impact index (default: "indexes/splade_v3_impact").
    SPLADE_PROVIDER : str, optional
        Default ONNX Runtime execution provider (default: "CPUExecutionProvider").
    SPLADE_QUANTIZATION : int, optional
        Integer quantization factor applied during SPLADE encoding (default: 100).
    SPLADE_MAX_TERMS : int, optional
        Maximum SPLADE query terms retained after expansion (default: 3000).
    SPLADE_MAX_CLAUSE : int, optional
        Lucene Boolean clause limit used while indexing SPLADE vectors (default: 4096).
    SPLADE_BATCH_SIZE : int, optional
        Default batch size for SPLADE encoding CLI commands (default: 32).
    CODERANK_MODEL_ID : str, optional
        Hugging Face identifier for CodeRank embeddings (default: "nomic-ai/CodeRankEmbed").
    CODERANK_TRUST_REMOTE_CODE : str, optional
        Allow custom code from the model repo ("1"/"true" to enable, default enabled).
    CODERANK_DEVICE : str, optional
        Device string for CodeRank embeddings (default: "cpu").
    CODERANK_BATCH : int, optional
        Batch size for CodeRank encoding (default: 128).
    CODERANK_NORMALIZE : str, optional
        Enable L2 normalization for CodeRank embeddings (default enabled).
    CODERANK_QUERY_PREFIX : str, optional
        Override the CodeRank instruction prefix when necessary.
    CODERANK_VECTORS_DIR : str, optional
        Storage directory for CodeRank vectors (default: "data/coderank_vectors").
    CODERANK_FAISS_INDEX : str, optional
        CodeRank FAISS index path (default: "data/faiss/coderank.ivfpq.faiss").
    WARP_INDEX_DIR : str, optional
        Directory containing WARP/XTR index artifacts (default: "indexes/warp_xtr").
    WARP_MODEL_ID : str, optional
        Identifier for WARP's multivector encoder (default: "intfloat/e5-multivector-large").
    WARP_DEVICE : str, optional
        Device for the WARP executor (default: "cpu").
    WARP_TOP_K : int, optional
        Candidate fan-out requested from WARP (default: 200).
    WARP_ENABLED : str, optional
        Enable WARP channel ("1"/"true" to enable, default disabled).
    XTR_DIR : str, optional
        Directory containing XTR token artifacts (default: "data/xtr").
    XTR_MODEL_ID : str, optional
        Encoder checkpoint for XTR tokens (default: "nomic-ai/CodeRankEmbed").
    XTR_DEVICE : str, optional
        Device for XTR query encoding ("cuda" default).
    XTR_MAX_QUERY_TOKENS : int, optional
        Maximum number of query tokens processed (default: 256).
    XTR_CANDIDATE_K : int, optional
        Number of Stage-A candidates to rescore (default: 200).
    XTR_DIM : int, optional
        Token embedding dimensionality (default: 768).
    XTR_DTYPE : str, optional
        Token storage dtype ("float16" default).
    XTR_ENABLE : str, optional
        Enable XTR rescoring ("1"/"true" to enable, default disabled).
    CODERANK_LLM_MODEL_ID : str, optional
        Identifier for the CodeRank listwise reranker (default: "nomic-ai/CodeRankLLM").
    CODERANK_LLM_DEVICE : str, optional
        Device for the listwise reranker (default: "cpu").
    CODERANK_LLM_MAX_NEW_TOKENS : int, optional
        Max tokens generated when reranking (default: 256).
    CODERANK_LLM_TEMPERATURE : float, optional
        Sampling temperature for reranker generations (default: 0.0).
    CODERANK_LLM_TOP_P : float, optional
        Top-p nucleus sampling parameter (default: 1.0).
    CODERANK_LLM_ENABLED : str, optional
        Enable the CodeRank listwise reranker ("1"/"true" to enable, default disabled).
    """
    repo_root = os.environ.get("REPO_ROOT", str(Path.cwd()))

    vllm = _build_vllm_config()
    paths = _build_paths_config(repo_root)

    rrf_weights = _load_rrf_weights()
    hybrid_prefetch = _load_hybrid_prefetch()
    hybrid_weights_override = _load_hybrid_weights_override()
    prf_config = _build_prf_config()
    channel_settings = _load_hybrid_channel_settings()

    index = _build_index_config(
        rrf_weights=rrf_weights,
        hybrid_prefetch=hybrid_prefetch,
        hybrid_weights_override=hybrid_weights_override,
        prf_config=prf_config,
        channel_settings=channel_settings,
    )

    limits = _build_server_limits()
    redis = _build_redis_config()
    duckdb_config = _build_duckdb_config()
    eval_config = _build_eval_config()

    return Settings(
        vllm=vllm,
        paths=paths,
        index=index,
        limits=limits,
        redis=redis,
        duckdb=duckdb_config,
        bm25=_build_bm25_config(
            enabled=channel_settings.bm25_enabled,
            bm25_k1=channel_settings.bm25_k1,
            bm25_b=channel_settings.bm25_b,
            prf_config=prf_config,
        ),
        splade=_build_splade_config(enabled=channel_settings.splade_enabled),
        coderank=_build_coderank_config(),
        warp=_build_warp_config(),
        xtr=_build_xtr_config(),
        rerank=_build_rerank_config(),
        coderank_llm=_build_coderank_llm_config(),
        eval=eval_config,
    )


def _build_paths_config(repo_root: str) -> PathsConfig:
    return PathsConfig(
        repo_root=repo_root,
        data_dir=os.environ.get("DATA_DIR", "data"),
        vectors_dir=os.environ.get("VECTORS_DIR", "data/vectors"),
        faiss_index=os.environ.get("FAISS_INDEX", "data/faiss/code.ivfpq.faiss"),
        faiss_idmap_path=os.environ.get("FAISS_IDMAP_PATH", "data/faiss/faiss_idmap.parquet"),
        lucene_dir=os.environ.get("LUCENE_DIR", "data/lucene"),
        splade_dir=os.environ.get("SPLADE_DIR", "data/splade"),
        duckdb_path=os.environ.get("DUCKDB_PATH", "data/catalog.duckdb"),
        scip_index=os.environ.get("SCIP_INDEX", "index.scip"),
        coderank_vectors_dir=os.environ.get("CODERANK_VECTORS_DIR", "data/coderank_vectors"),
        coderank_faiss_index=os.environ.get(
            "CODERANK_FAISS_INDEX",
            "data/faiss/coderank.ivfpq.faiss",
        ),
        warp_index_dir=os.environ.get("WARP_INDEX_DIR", "indexes/warp_xtr"),
        xtr_dir=os.environ.get("XTR_DIR", "data/xtr"),
    )


def _load_rrf_weights() -> dict[str, float]:
    weights = dict(DEFAULT_RRF_WEIGHTS)
    payload = os.environ.get("RRF_WEIGHTS_JSON")
    if not payload:
        return weights
    try:
        parsed = json.loads(payload)
    except (json.JSONDecodeError, TypeError, ValueError):
        return weights
    if isinstance(parsed, dict):
        parsed_weights: dict[str, float] = {}
        for channel, weight in parsed.items():
            try:
                parsed_weights[str(channel)] = float(weight)
            except (TypeError, ValueError):
                continue
        if parsed_weights:
            return parsed_weights
    return weights


def _load_hybrid_prefetch() -> dict[str, int]:
    default_prefetch = {"semantic": 200, "bm25": 200, "splade": 200}
    payload = os.environ.get("HYBRID_PREFETCH_JSON")
    if not payload:
        return default_prefetch
    try:
        parsed = json.loads(payload)
    except (json.JSONDecodeError, TypeError, ValueError):
        return default_prefetch
    if isinstance(parsed, dict):
        parsed_dict: dict[str, int] = {}
        for key, value in parsed.items():
            try:
                parsed_dict[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
        if parsed_dict:
            return parsed_dict
    return default_prefetch


def _load_hybrid_weights_override() -> dict[str, float]:
    payload = os.environ.get("HYBRID_WEIGHTS_OVERRIDE_JSON")
    if not payload:
        return {}
    try:
        parsed = json.loads(payload)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    if isinstance(parsed, dict):
        weights: dict[str, float] = {}
        for channel, weight in parsed.items():
            try:
                weights[str(channel)] = float(weight)
            except (TypeError, ValueError):
                continue
        return weights
    return {}


def _build_prf_config() -> PRFConfig:
    return PRFConfig(
        enable_auto=_env_bool("BM25_PRF_ENABLE_AUTO", default=True),
        fb_docs=int(os.environ.get("BM25_PRF_FB_DOCS", "10")),
        fb_terms=int(os.environ.get("BM25_PRF_FB_TERMS", "10")),
        orig_weight=float(os.environ.get("BM25_PRF_ORIG_WEIGHT", "0.5")),
        short_query_max_terms=int(os.environ.get("BM25_PRF_SHORT_QUERY_MAX_TERMS", "3")),
        symbol_like_regex=os.environ.get("BM25_PRF_SYMBOL_REGEX"),
        head_terms_csv=os.environ.get("BM25_PRF_HEAD_TERMS_CSV"),
    )


def _load_hybrid_channel_settings() -> _HybridChannelSettings:
    return _HybridChannelSettings(
        bm25_enabled=_env_bool("HYBRID_ENABLE_BM25", default=True),
        splade_enabled=_env_bool("HYBRID_ENABLE_SPLADE", default=True),
        bm25_k1=float(os.environ.get("BM25_K1", "0.9")),
        bm25_b=float(os.environ.get("BM25_B", "0.4")),
    )


def _build_index_config(
    *,
    rrf_weights: dict[str, float],
    hybrid_prefetch: dict[str, int],
    hybrid_weights_override: dict[str, float],
    prf_config: PRFConfig,
    channel_settings: _HybridChannelSettings,
) -> IndexConfig:
    recency_enabled = _env_bool("INDEX_RECENCY_ENABLED")
    recency_half_life_days = float(os.environ.get("INDEX_RECENCY_HALF_LIFE_DAYS", "30.0"))
    recency_max_boost = float(os.environ.get("INDEX_RECENCY_MAX_BOOST", "0.15"))
    recency_table = os.environ.get("INDEX_RECENCY_TABLE", "chunks")
    return IndexConfig(
        vec_dim=int(os.environ.get("VEC_DIM", "2560")),
        chunk_budget=int(os.environ.get("CHUNK_BUDGET", "2200")),
        faiss_nlist=int(os.environ.get("FAISS_NLIST", "8192")),
        faiss_nprobe=int(os.environ.get("FAISS_NPROBE", "128")),
        bm25_k1=channel_settings.bm25_k1,
        bm25_b=channel_settings.bm25_b,
        rrf_k=int(os.environ.get("RRF_K", "60")),
        enable_bm25_channel=channel_settings.bm25_enabled,
        enable_splade_channel=channel_settings.splade_enabled,
        hybrid_top_k_per_channel=int(os.environ.get("HYBRID_TOP_K_PER_CHANNEL", "50")),
        use_cuvs=_env_bool("USE_CUVS", default=True),
        faiss_preload=_env_bool("FAISS_PRELOAD"),
        duckdb_materialize=_env_bool("DUCKDB_MATERIALIZE"),
        preview_max_chars=int(os.environ.get("PREVIEW_MAX_CHARS", "240")),
        compaction_threshold=float(os.environ.get("FAISS_COMPACTION_THRESHOLD", "0.05")),
        rrf_weights=rrf_weights,
        hybrid_prefetch=hybrid_prefetch,
        hybrid_use_rrf=_env_bool("HYBRID_USE_RRF", default=True),
        hybrid_weights_override=hybrid_weights_override,
        prf=prf_config,
        recency_enabled=recency_enabled,
        recency_half_life_days=recency_half_life_days,
        recency_max_boost=recency_max_boost,
        recency_table=recency_table,
    )


def _build_server_limits() -> ServerLimits:
    return ServerLimits(
        max_results=int(os.environ.get("MAX_RESULTS", "1000")),
        query_timeout_s=float(os.environ.get("QUERY_TIMEOUT_S", "30.0")),
        rate_limit_qps=float(os.environ.get("RATE_LIMIT_QPS", "10.0")),
        rate_limit_burst=int(os.environ.get("RATE_LIMIT_BURST", "20")),
        semantic_overfetch_multiplier=int(os.environ.get("SEMANTIC_OVERFETCH_MULTIPLIER", "2")),
    )


def _build_redis_config() -> RedisConfig:
    defaults = RedisConfig()
    return RedisConfig(
        url=os.environ.get("REDIS_URL", defaults.url),
        scope_l1_size=int(os.environ.get("REDIS_SCOPE_L1_SIZE", str(defaults.scope_l1_size))),
        scope_l1_ttl_seconds=float(
            os.environ.get("REDIS_SCOPE_L1_TTL_SECONDS", str(defaults.scope_l1_ttl_seconds))
        ),
        scope_l2_ttl_seconds=int(
            os.environ.get("REDIS_SCOPE_L2_TTL_SECONDS", str(defaults.scope_l2_ttl_seconds))
        ),
    )


def _build_duckdb_config() -> DuckDBConfig:
    defaults = DuckDBConfig()
    pool_env = os.environ.get("DUCKDB_POOL_SIZE")
    pool_size = (
        None
        if pool_env is None or not pool_env.strip() or pool_env.strip() == "0"
        else int(pool_env)
    )
    return DuckDBConfig(
        threads=int(os.environ.get("DUCKDB_THREADS", str(defaults.threads))),
        enable_object_cache=_env_bool("DUCKDB_OBJECT_CACHE", default=True),
        log_queries=_env_bool("DUCKDB_LOG_QUERIES"),
        pool_size=pool_size,
    )


def _build_eval_config() -> EvalConfig:
    return EvalConfig(
        enabled=_env_bool("EVAL_ENABLED"),
        queries_path=os.environ.get("EVAL_QUERIES_PATH"),
        output_dir=os.environ.get("EVAL_OUTPUT_DIR", "artifacts/eval"),
        k_values=_parse_int_list(os.environ.get("EVAL_K_VALUES"), (5, 10, 20)),
        max_queries=_optional_int(os.environ.get("EVAL_MAX_QUERIES")),
        oracle_top_k=int(os.environ.get("EVAL_ORACLE_TOP_K", "50")),
        xtr_as_oracle=_env_bool("EVAL_XTR_AS_ORACLE"),
    )


def _resolve_bm25_analyzer(raw: str | None) -> Literal["code", "standard"]:
    normalized = (raw or "code").strip().lower()
    if normalized == "standard":
        return "standard"
    return "code"


def _resolve_splade_analyzer(raw: str | None) -> Literal["wordpiece", "code"]:
    normalized = (raw or "wordpiece").strip().lower()
    if normalized == "code":
        return "code"
    return "wordpiece"


def _build_bm25_config(
    *,
    enabled: bool,
    bm25_k1: float,
    bm25_b: float,
    prf_config: PRFConfig,
) -> BM25Config:
    analyzer_value = _resolve_bm25_analyzer(os.environ.get("BM25_ANALYZER", "code"))
    return BM25Config(
        corpus_json_dir=os.environ.get("BM25_JSONL_DIR", "data/jsonl"),
        index_dir=os.environ.get("BM25_INDEX_DIR", "indexes/bm25"),
        threads=int(os.environ.get("BM25_THREADS", "8")),
        enabled=enabled,
        k1=bm25_k1,
        b=bm25_b,
        rm3_enabled=_env_bool("BM25_RM3_ENABLED"),
        rm3_fb_docs=int(os.environ.get("BM25_RM3_FB_DOCS", str(prf_config.fb_docs))),
        rm3_fb_terms=int(os.environ.get("BM25_RM3_FB_TERMS", str(prf_config.fb_terms))),
        rm3_original_query_weight=float(
            os.environ.get(
                "BM25_RM3_ORIG_WEIGHT",
                str(prf_config.orig_weight),
            )
        ),
        analyzer=analyzer_value,
        stopwords=tuple(
            word.strip() for word in os.environ.get("BM25_STOPWORDS", "").split(",") if word.strip()
        ),
    )


def _build_splade_config(*, enabled: bool) -> SpladeConfig:
    analyzer_value = _resolve_splade_analyzer(os.environ.get("SPLADE_ANALYZER", "wordpiece"))
    return SpladeConfig(
        model_id=os.environ.get("SPLADE_MODEL_ID", "naver/splade-v3"),
        model_dir=os.environ.get("SPLADE_MODEL_DIR", "models/splade-v3"),
        onnx_dir=os.environ.get("SPLADE_ONNX_DIR", "models/splade-v3/onnx"),
        onnx_file=os.environ.get("SPLADE_ONNX_FILE", "model_qint8.onnx"),
        vectors_dir=os.environ.get("SPLADE_VECTORS_DIR", "data/splade_vectors"),
        index_dir=os.environ.get("SPLADE_INDEX_DIR", "indexes/splade_v3_impact"),
        provider=os.environ.get("SPLADE_PROVIDER", "CPUExecutionProvider"),
        quantization=int(os.environ.get("SPLADE_QUANTIZATION", "100")),
        max_terms=int(os.environ.get("SPLADE_MAX_TERMS", "3000")),
        max_clause_count=int(os.environ.get("SPLADE_MAX_CLAUSE", "4096")),
        batch_size=int(os.environ.get("SPLADE_BATCH_SIZE", "32")),
        threads=int(os.environ.get("SPLADE_THREADS", "8")),
        enabled=enabled,
        max_query_terms=int(os.environ.get("SPLADE_MAX_QUERY_TERMS", "64")),
        prune_below=float(os.environ.get("SPLADE_PRUNE_BELOW", "0.0")),
        analyzer=analyzer_value,
        static_prune_pct=float(os.environ.get("SPLADE_STATIC_PRUNE_PCT", "0.0")),
    )


def _build_coderank_config() -> CodeRankConfig:
    return CodeRankConfig(
        model_id=os.environ.get("CODERANK_MODEL_ID", "nomic-ai/CodeRankEmbed"),
        trust_remote_code=_env_bool("CODERANK_TRUST_REMOTE_CODE", default=True),
        device=os.environ.get("CODERANK_DEVICE", "cpu"),
        batch_size=int(os.environ.get("CODERANK_BATCH", "128")),
        normalize=_env_bool("CODERANK_NORMALIZE", default=True),
        query_prefix=os.environ.get(
            "CODERANK_QUERY_PREFIX",
            "Represent this query for searching relevant code: ",
        ),
        top_k=int(os.environ.get("CODERANK_TOP_K", "200")),
        budget_ms=int(os.environ.get("CODERANK_BUDGET_MS", "120")),
        min_stage2_margin=float(os.environ.get("CODERANK_MARGIN_THRESHOLD", "0.1")),
        min_stage2_candidates=int(os.environ.get("CODERANK_MIN_STAGE2", "40")),
    )


def _build_warp_config() -> WarpConfig:
    return WarpConfig(
        index_dir=os.environ.get("WARP_INDEX_DIR", "indexes/warp_xtr"),
        model_id=os.environ.get("WARP_MODEL_ID", "intfloat/e5-multivector-large"),
        device=os.environ.get("WARP_DEVICE", "cpu"),
        top_k=int(os.environ.get("WARP_TOP_K", "200")),
        enabled=_env_bool("WARP_ENABLED"),
        budget_ms=int(os.environ.get("WARP_BUDGET_MS", "180")),
    )


def _build_coderank_llm_config() -> CodeRankLLMConfig:
    return CodeRankLLMConfig(
        model_id=os.environ.get("CODERANK_LLM_MODEL_ID", "nomic-ai/CodeRankLLM"),
        device=os.environ.get("CODERANK_LLM_DEVICE", "cpu"),
        max_new_tokens=int(os.environ.get("CODERANK_LLM_MAX_NEW_TOKENS", "256")),
        temperature=float(os.environ.get("CODERANK_LLM_TEMPERATURE", "0.0")),
        top_p=float(os.environ.get("CODERANK_LLM_TOP_P", "1.0")),
        enabled=_env_bool("CODERANK_LLM_ENABLED"),
        budget_ms=int(os.environ.get("CODERANK_LLM_BUDGET_MS", "300")),
    )


__all__ = [
    "BM25Config",
    "CodeRankConfig",
    "CodeRankLLMConfig",
    "IndexConfig",
    "PRFConfig",
    "PathsConfig",
    "RedisConfig",
    "RerankConfig",
    "ServerLimits",
    "Settings",
    "SpladeConfig",
    "VLLMConfig",
    "VLLMRunMode",
    "WarpConfig",
    "XTRConfig",
    "load_settings",
]
