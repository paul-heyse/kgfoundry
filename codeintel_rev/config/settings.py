"""Configuration settings using msgspec for fast, validated config.

NO Pydantic - using msgspec.Struct for performance-critical settings.
All configuration loaded from environment variables with sensible defaults.
"""

from __future__ import annotations

import os
from pathlib import Path

import msgspec

from codeintel_rev.io.duckdb_manager import DuckDBConfig


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
    """

    model_id: str = "nomic-ai/CodeRankEmbed"
    trust_remote_code: bool = True
    device: str = "cpu"
    batch_size: int = 128
    normalize: bool = True
    query_prefix: str = "Represent this query for searching relevant code: "


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
    """

    index_dir: str = "indexes/warp_xtr"
    model_id: str = "intfloat/e5-multivector-large"
    device: str = "cpu"
    top_k: int = 200
    enabled: bool = False


class CodeRankLLMConfig(msgspec.Struct, frozen=True):
    """Configuration for the CodeRank listwise reranker."""

    model_id: str = "nomic-ai/CodeRankLLM"
    device: str = "cpu"
    max_new_tokens: int = 256
    temperature: float = 0.0
    top_p: float = 1.0
    enabled: bool = False


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
    """

    base_url: str = "http://127.0.0.1:8001/v1"
    model: str = "nomic-ai/nomic-embed-code"
    batch_size: int = 64
    embedding_dim: int = 2560
    timeout_s: float = 120.0


class BM25Config(msgspec.Struct, frozen=True):
    """BM25 indexing and search configuration.

    Attributes
    ----------
    corpus_json_dir : str
        Directory containing per-document JSON files used to build the BM25 index.
        Defaults to ``data/jsonl`` (relative to ``paths.repo_root``).
    index_dir : str
        Output directory for the Lucene index. Defaults to ``indexes/bm25``.
    threads : int
        Number of worker threads to use while building the index. Defaults to 8.
    """

    corpus_json_dir: str = "data/jsonl"
    index_dir: str = "indexes/bm25"
    threads: int = 8


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
    """

    repo_root: str
    data_dir: str = "data"
    vectors_dir: str = "data/vectors"
    faiss_index: str = "data/faiss/code.ivfpq.faiss"
    lucene_dir: str = "data/lucene"
    splade_dir: str = "data/splade"
    duckdb_path: str = "data/catalog.duckdb"
    scip_index: str = "index.scip"
    coderank_vectors_dir: str = "data/coderank_vectors"
    coderank_faiss_index: str = "data/faiss/coderank.ivfpq.faiss"
    warp_index_dir: str = "indexes/warp_xtr"


class IndexConfig(msgspec.Struct, frozen=True):
    """Indexing and search configuration.

    Configuration parameters for the indexing pipeline and search algorithms.
    This includes settings for chunking, vector dimensions, FAISS index structure,
    BM25 parameters, and hybrid retrieval fusion.

    The configuration balances search quality (recall/precision) with performance
    (index size, search speed). The defaults are tuned for code search workloads
    with typical repository sizes (thousands to millions of chunks).

    Attributes
    ----------
    vec_dim : int
        Dimensionality of embedding vectors. Must match the embedding model's
        output dimension and stay aligned with :class:`VLLMConfig` ``embedding_dim``.
        Defaults to 2560 for nomic-embed-code model. Changing this requires
        re-indexing with a different model.
    chunk_budget : int
        Target chunk size in characters. The cAST chunker tries to pack symbols
        up to this size before splitting. Larger chunks provide more context but
        may reduce precision. Defaults to 2200 characters, which is optimal for
        code search (roughly 50-100 lines depending on code style).
    faiss_nlist : int
        Number of IVF (Inverted File) centroids/clusters. More centroids improve
        recall but increase index size and training time. Defaults to 8192, which
        provides good recall for millions of vectors. For smaller datasets (<100k),
        consider 4096; for very large (>10M), consider 16384.
    faiss_nprobe : int
        Number of IVF cells to probe during live semantic search queries. Higher
        values improve recall but increase response latency. Defaults to 128,
        which probes ~1.5% of cells for nlist=8192. For higher recall, increase
        to 256 or 512; for faster searches, decrease to 64.
    bm25_k1 : float
        BM25 term frequency saturation parameter. Controls how quickly term
        frequency saturates. Higher values (1.0-2.0) give more weight to
        repeated terms. Defaults to 0.9, which is standard for code search.
    bm25_b : float
        BM25 length normalization parameter. Controls how much document length
        affects scoring (0 = no normalization, 1 = full normalization).
        Defaults to 0.4, which provides moderate length normalization suitable
        for code where length varies significantly.
    rrf_k : int
        Reciprocal Rank Fusion (RRF) K parameter. Used to fuse results from
        multiple retrieval systems (FAISS, BM25, SPLADE). Higher K values give
        more weight to lower-ranked results. Defaults to 60, which is standard
        for hybrid search. Lower values (30-40) favor top results; higher (80-100)
        give more weight to consensus across systems.
    enable_bm25_channel : bool
        Enable BM25 channel when performing hybrid retrieval. When disabled, BM25
        results are excluded from fusion but the index can still be built for
        other workflows. Defaults to ``True``.
    enable_splade_channel : bool
        Enable SPLADE channel when performing hybrid retrieval. When disabled,
        SPLADE results are excluded from fusion. Defaults to ``True``.
    hybrid_top_k_per_channel : int
        Per-channel cutoff used when gathering candidates before RRF fusion.
        Defaults to 50, which balances coverage with latency.
    use_cuvs : bool
        Enable cuVS (CUDA Vector Search) acceleration for FAISS GPU operations.
        cuVS provides optimized GPU kernels that can be 2-3x faster than standard
        FAISS GPU. Requires libcuvs-cu13 package. Defaults to True. Set to False
        if cuVS is unavailable or causes issues.
    faiss_preload : bool
        Pre-load FAISS index during application startup (eager loading). When True,
        the FAISS index is loaded immediately at startup, eliminating first-request
        latency. When False (default), the index is loaded lazily on first semantic
        search request. Set to True in production for consistent response times;
        keep False in development for faster startup iteration.
    duckdb_materialize : bool
        Persist chunk metadata into a DuckDB table (``chunks_materialized``) to
        enable secondary indexes. When ``False`` (default), the catalog exposes
        Parquet files via a view for zero-copy reads. Enable this for very large
        catalogs when SQL filtering requires indexes. Defaults to ``False``.
    preview_max_chars : int
        Maximum number of characters to persist in the Parquet ``preview`` column.
        This controls indexing-time truncation. Defaults to 240 characters.
    compaction_threshold : float
        Fraction of primary index size that the secondary index can reach before a
        compaction is recommended. Defaults to 0.05 (5%).
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
    coderank_llm : CodeRankLLMConfig
        CodeRank listwise reranker configuration.
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
    coderank_llm: CodeRankLLMConfig


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

    vllm = VLLMConfig(
        base_url=os.environ.get("VLLM_URL", "http://127.0.0.1:8001/v1"),
        model=os.environ.get("VLLM_MODEL", "nomic-ai/nomic-embed-code"),
        batch_size=int(os.environ.get("VLLM_BATCH_SIZE", "64")),
        timeout_s=float(os.environ.get("VLLM_TIMEOUT_S", "120.0")),
        embedding_dim=int(os.environ.get("VLLM_EMBED_DIM", "2560")),
    )

    paths = PathsConfig(
        repo_root=repo_root,
        data_dir=os.environ.get("DATA_DIR", "data"),
        vectors_dir=os.environ.get("VECTORS_DIR", "data/vectors"),
        faiss_index=os.environ.get("FAISS_INDEX", "data/faiss/code.ivfpq.faiss"),
        lucene_dir=os.environ.get("LUCENE_DIR", "data/lucene"),
        splade_dir=os.environ.get("SPLADE_DIR", "data/splade"),
        duckdb_path=os.environ.get("DUCKDB_PATH", "data/catalog.duckdb"),
        scip_index=os.environ.get("SCIP_INDEX", "index.scip"),
        coderank_vectors_dir=os.environ.get("CODERANK_VECTORS_DIR", "data/coderank_vectors"),
        coderank_faiss_index=os.environ.get(
            "CODERANK_FAISS_INDEX", "data/faiss/coderank.ivfpq.faiss"
        ),
        warp_index_dir=os.environ.get("WARP_INDEX_DIR", "indexes/warp_xtr"),
    )

    index = IndexConfig(
        vec_dim=int(os.environ.get("VEC_DIM", "2560")),
        chunk_budget=int(os.environ.get("CHUNK_BUDGET", "2200")),
        faiss_nlist=int(os.environ.get("FAISS_NLIST", "8192")),
        faiss_nprobe=int(os.environ.get("FAISS_NPROBE", "128")),
        bm25_k1=float(os.environ.get("BM25_K1", "0.9")),
        bm25_b=float(os.environ.get("BM25_B", "0.4")),
        rrf_k=int(os.environ.get("RRF_K", "60")),
        enable_bm25_channel=os.environ.get("HYBRID_ENABLE_BM25", "1").lower()
        in {"1", "true", "yes"},
        enable_splade_channel=os.environ.get("HYBRID_ENABLE_SPLADE", "1").lower()
        in {"1", "true", "yes"},
        hybrid_top_k_per_channel=int(os.environ.get("HYBRID_TOP_K_PER_CHANNEL", "50")),
        use_cuvs=os.environ.get("USE_CUVS", "1").lower() in {"1", "true", "yes"},
        faiss_preload=os.environ.get("FAISS_PRELOAD", "0").lower() in {"1", "true", "yes"},
        duckdb_materialize=os.environ.get("DUCKDB_MATERIALIZE", "0").lower()
        in {"1", "true", "yes"},
        preview_max_chars=int(os.environ.get("PREVIEW_MAX_CHARS", "240")),
        compaction_threshold=float(os.environ.get("FAISS_COMPACTION_THRESHOLD", "0.05")),
    )

    limits = ServerLimits(
        max_results=int(os.environ.get("MAX_RESULTS", "1000")),
        query_timeout_s=float(os.environ.get("QUERY_TIMEOUT_S", "30.0")),
        rate_limit_qps=float(os.environ.get("RATE_LIMIT_QPS", "10.0")),
        rate_limit_burst=int(os.environ.get("RATE_LIMIT_BURST", "20")),
        semantic_overfetch_multiplier=int(os.environ.get("SEMANTIC_OVERFETCH_MULTIPLIER", "2")),
    )

    redis_defaults = RedisConfig()
    redis = RedisConfig(
        url=os.environ.get("REDIS_URL", redis_defaults.url),
        scope_l1_size=int(os.environ.get("REDIS_SCOPE_L1_SIZE", str(redis_defaults.scope_l1_size))),
        scope_l1_ttl_seconds=float(
            os.environ.get("REDIS_SCOPE_L1_TTL_SECONDS", str(redis_defaults.scope_l1_ttl_seconds))
        ),
        scope_l2_ttl_seconds=int(
            os.environ.get("REDIS_SCOPE_L2_TTL_SECONDS", str(redis_defaults.scope_l2_ttl_seconds))
        ),
    )

    duckdb_defaults = DuckDBConfig()
    duckdb_pool_env = os.environ.get("DUCKDB_POOL_SIZE")
    duckdb_pool_size = (
        None
        if duckdb_pool_env is None or not duckdb_pool_env.strip() or duckdb_pool_env.strip() == "0"
        else int(duckdb_pool_env)
    )
    duckdb_config = DuckDBConfig(
        threads=int(os.environ.get("DUCKDB_THREADS", str(duckdb_defaults.threads))),
        enable_object_cache=os.environ.get("DUCKDB_OBJECT_CACHE", "1").lower()
        in {
            "1",
            "true",
            "yes",
        },
        log_queries=os.environ.get("DUCKDB_LOG_QUERIES", "0").lower()
        in {
            "1",
            "true",
            "yes",
        },
        pool_size=duckdb_pool_size,
    )

    return Settings(
        vllm=vllm,
        paths=paths,
        index=index,
        limits=limits,
        redis=redis,
        duckdb=duckdb_config,
        bm25=BM25Config(
            corpus_json_dir=os.environ.get("BM25_JSONL_DIR", "data/jsonl"),
            index_dir=os.environ.get("BM25_INDEX_DIR", "indexes/bm25"),
            threads=int(os.environ.get("BM25_THREADS", "8")),
        ),
        splade=SpladeConfig(
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
        ),
        coderank=CodeRankConfig(
            model_id=os.environ.get("CODERANK_MODEL_ID", "nomic-ai/CodeRankEmbed"),
            trust_remote_code=os.environ.get("CODERANK_TRUST_REMOTE_CODE", "1").lower()
            in {"1", "true", "yes"},
            device=os.environ.get("CODERANK_DEVICE", "cpu"),
            batch_size=int(os.environ.get("CODERANK_BATCH", "128")),
            normalize=os.environ.get("CODERANK_NORMALIZE", "1").lower() in {"1", "true", "yes"},
            query_prefix=os.environ.get(
                "CODERANK_QUERY_PREFIX",
                "Represent this query for searching relevant code: ",
            ),
        ),
        warp=WarpConfig(
            index_dir=os.environ.get("WARP_INDEX_DIR", "indexes/warp_xtr"),
            model_id=os.environ.get("WARP_MODEL_ID", "intfloat/e5-multivector-large"),
            device=os.environ.get("WARP_DEVICE", "cpu"),
            top_k=int(os.environ.get("WARP_TOP_K", "200")),
            enabled=os.environ.get("WARP_ENABLED", "0").lower() in {"1", "true", "yes"},
        ),
        coderank_llm=CodeRankLLMConfig(
            model_id=os.environ.get("CODERANK_LLM_MODEL_ID", "nomic-ai/CodeRankLLM"),
            device=os.environ.get("CODERANK_LLM_DEVICE", "cpu"),
            max_new_tokens=int(os.environ.get("CODERANK_LLM_MAX_NEW_TOKENS", "256")),
            temperature=float(os.environ.get("CODERANK_LLM_TEMPERATURE", "0.0")),
            top_p=float(os.environ.get("CODERANK_LLM_TOP_P", "1.0")),
            enabled=os.environ.get("CODERANK_LLM_ENABLED", "0").lower() in {"1", "true", "yes"},
        ),
    )


__all__ = [
    "BM25Config",
    "CodeRankConfig",
    "CodeRankLLMConfig",
    "IndexConfig",
    "PathsConfig",
    "RedisConfig",
    "ServerLimits",
    "Settings",
    "SpladeConfig",
    "VLLMConfig",
    "WarpConfig",
    "load_settings",
]
