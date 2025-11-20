"""Immutable, versioned configuration data models."""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Literal

CONFIG_API_VERSION: Final[str] = "1.0"


def _require(message: str, *, condition: bool) -> None:
    """Raise ValueError when ``condition`` is False.

    Parameters
    ----------
    message : str
        Error message to include in the exception.
    condition : bool
        Condition to check. If False, ValueError is raised.

    Raises
    ------
    ValueError
        If ``condition`` is False.
    """
    if not condition:
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class PathsConfig:
    """Filesystem paths used by the application.

    Attributes
    ----------
    repo_root : Path
        Repository root directory path. All other paths are typically resolved
        relative to this root.
    data_dir : Path
        Directory path for application data files (indexes, catalogs, etc.).
    cache_dir : Path
        Directory path for cached artifacts and temporary data.
    logs_dir : Path
        Directory path for application log files.
    """

    repo_root: Path
    data_dir: Path
    cache_dir: Path
    logs_dir: Path


@dataclass(frozen=True, slots=True)
class DuckDBSettings:
    """Settings for the DuckDB subsystem.

    Attributes
    ----------
    database : Path
        Path to the DuckDB database file. Used for catalog storage and queries.
    threads : int | None, optional
        Number of threads for DuckDB operations. If None, uses DuckDB's default
        thread count. Defaults to None.
    object_cache : bool, optional
        Whether to enable DuckDB's object cache for improved performance.
        Defaults to True.
    temp_directory : Path | None, optional
        Optional temporary directory for DuckDB operations. If None, uses DuckDB's
        default temporary directory. Defaults to None.
    pool_size : int, optional
        Connection pool size for concurrent DuckDB operations. Defaults to 4.
    """

    database: Path
    threads: int | None = None
    object_cache: bool = True
    temp_directory: Path | None = None
    pool_size: int = 4


@dataclass(frozen=True, slots=True)
class FAISSSettings:
    """Settings for the FAISS subsystem.

    Attributes
    ----------
    index_path : Path
        Path to the FAISS index file. The index must exist and be compatible
        with the configured vector dimension.
    default_k : int, optional
        Default number of nearest neighbors to retrieve in FAISS searches.
        Defaults to 50.
    default_nprobe : int, optional
        Default number of clusters to probe in IVF indexes. Higher values
        improve recall but increase search time. Defaults to 64.
    refine_k_factor : float, optional
        Multiplier for refinement during FAISS search. Values > 1.0 retrieve
        more candidates before refinement. Defaults to 1.0.
    """

    index_path: Path
    default_k: int = 50
    default_nprobe: int = 64
    refine_k_factor: float = 1.0


@dataclass(frozen=True, slots=True)
class SearchSettings:
    """Settings for hybrid search weighting and Stage-0 tuning.

    Attributes
    ----------
    bm25_weight : float, optional
        Weight for BM25 sparse retrieval channel in hybrid fusion. Must be
        non-negative. Defaults to 0.2.
    splade_weight : float, optional
        Weight for SPLADE sparse retrieval channel in hybrid fusion. Must be
        non-negative. Defaults to 0.3.
    faiss_weight : float, optional
        Weight for FAISS dense retrieval channel in hybrid fusion. Must be
        non-negative. Defaults to 0.5.
    per_channel_k : int, optional
        Number of results to retrieve from each channel before fusion. Larger
        values improve recall but increase computation. Defaults to 100.
    fusion_k : int, optional
        Number of results to return after fusion. Must be positive. Defaults to 50.
    rrf_base : int, optional
        Base value for Reciprocal Rank Fusion (RRF) scoring. Must be positive.
        Higher values reduce the impact of rank differences. Defaults to 60.
    max_results : int, optional
        Maximum number of results to return from search operations. Must be
        positive. Defaults to 50.
    """

    bm25_weight: float = 0.2
    splade_weight: float = 0.3
    faiss_weight: float = 0.5
    per_channel_k: int = 100
    fusion_k: int = 50
    rrf_base: int = 60
    max_results: int = 50


@dataclass(frozen=True, slots=True)
class PRFSettings:
    """Pseudo-relevance feedback (RM3) configuration."""

    enable_auto: bool = True
    fb_docs: int = 10
    fb_terms: int = 10
    orig_weight: float = 0.5
    short_query_max_terms: int = 3
    symbol_like_regex: str | None = None
    head_terms_csv: str | None = None


@dataclass(frozen=True, slots=True)
class IndexSettings:
    """Index build/search knobs spanning FAISS, BM25, SPLADE, and hybrid fusion."""

    vec_dim: int = 3584
    chunk_budget: int = 2200
    faiss_nlist: int = 8192
    faiss_nprobe: int = 128
    bm25_k1: float = 0.9
    bm25_b: float = 0.4
    rrf_k: int = 60
    enable_bm25_channel: bool = True
    enable_splade_channel: bool = True
    hybrid_top_k_per_channel: int = 50
    faiss_preload: bool = False
    duckdb_materialize: bool = False
    preview_max_chars: int = 240
    compaction_threshold: float = 0.05
    rrf_weights: Mapping[str, float] = field(
        default_factory=lambda: {"semantic": 1.0, "bm25": 1.0, "splade": 1.0, "warp": 1.1}
    )
    hybrid_prefetch: Mapping[str, int] = field(
        default_factory=lambda: {"semantic": 200, "bm25": 200, "splade": 200}
    )
    hybrid_use_rrf: bool = True
    hybrid_weights_override: Mapping[str, float] = field(default_factory=dict)
    prf: PRFSettings = field(default_factory=PRFSettings)
    recency_enabled: bool = False
    recency_half_life_days: float = 30.0
    recency_max_boost: float = 0.15
    recency_table: str = "chunks"
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
    refine_k_factor: float = 2.0
    autotune_on_start: bool = False
    enable_range_search: bool = False
    semantic_min_score: float = 0.0

    def __post_init__(self) -> None:
        """Normalize optional FAISS knobs with legacy fallbacks."""
        nlist_value = self.nlist or self.faiss_nlist
        default_nprobe_value = self.default_nprobe or self.faiss_nprobe
        object.__setattr__(self, "nlist", nlist_value)
        object.__setattr__(self, "default_nprobe", default_nprobe_value)


@dataclass(frozen=True, slots=True)
class ServerLimits:
    """Server resource and rate limits."""

    max_results: int = 1000
    query_timeout_s: float = 30.0
    rate_limit_qps: float = 10.0
    rate_limit_burst: int = 20
    semantic_overfetch_multiplier: int = 2


@dataclass(frozen=True, slots=True)
class RedisSettings:
    """Redis-backed scope cache configuration."""

    url: str = "redis://127.0.0.1:6379/0"
    scope_l1_size: int = 256
    scope_l1_ttl_seconds: float = 300.0
    scope_l2_ttl_seconds: int = 3600


@dataclass(frozen=True, slots=True)
class RerankSettings:
    """Late-interaction reranker configuration."""

    enabled: bool = False
    top_k: int = 50
    provider: Literal["xtr"] = "xtr"
    explain: bool = False


@dataclass(frozen=True, slots=True)
class LoggingSettings:
    """Settings for log output.

    Attributes
    ----------
    level : str, optional
        Logging level (e.g., "DEBUG", "INFO", "WARNING", "ERROR"). Must be
        a valid Python logging level name. Defaults to "INFO".
    json : bool, optional
        Whether to output logs in JSON format for structured logging. If False,
        logs are output in human-readable format. Defaults to False.
    """

    level: str = "INFO"
    json: bool = False


@dataclass(frozen=True, slots=True)
class EvalSettings:
    """Offline evaluation configuration."""

    enabled: bool = False
    queries_path: Path | None = None
    output_dir: Path = Path("artifacts") / "eval"
    k_values: tuple[int, ...] = (5, 10, 20)
    max_queries: int | None = None
    oracle_top_k: int = 50
    xtr_as_oracle: bool = False


@dataclass(frozen=True, slots=True)
class SpladeOnnxQueryConfig:
    """Optional SPLADE ONNX query encoder configuration.

    Attributes
    ----------
    enabled : bool, optional
        Whether to enable ONNX-based query encoding. If False, SPLADE query
        encoding uses the default PyTorch model. Defaults to False.
    model_path : Path | None, optional
        Path to the ONNX model file for query encoding. Required if enabled=True.
        Defaults to None.
    tokenizer_name : str | None, optional
        HuggingFace tokenizer name for the ONNX model. If None, inferred from
        model_path. Defaults to None.
    output_name : str, optional
        Name of the ONNX model output tensor containing logits. Defaults to "logits".
    input_ids_name : str, optional
        Name of the ONNX model input tensor for token IDs. Defaults to "input_ids".
    attention_mask_name : str, optional
        Name of the ONNX model input tensor for attention masks. Defaults to
        "attention_mask".
    providers : tuple[str, ...], optional
        ONNX Runtime execution providers (e.g., "CPUExecutionProvider",
        "CUDAExecutionProvider"). Defaults to ("CPUExecutionProvider",).
    topn : int, optional
        Number of top tokens to extract from SPLADE logits. Must be positive.
        Defaults to 64.
    min_weight : float, optional
        Minimum token weight threshold for filtering SPLADE tokens. Tokens
        below this threshold are discarded. Defaults to 1e-6.
    normalize : bool, optional
        Whether to normalize SPLADE token weights. Defaults to False.
    format : Literal["string", "map"], optional
        Output format for SPLADE queries. "string" produces a query string,
        "map" produces a token-to-weight mapping. Defaults to "string".
    """

    enabled: bool = False
    model_path: Path | None = None
    tokenizer_name: str | None = None
    output_name: str = "logits"
    input_ids_name: str = "input_ids"
    attention_mask_name: str = "attention_mask"
    providers: tuple[str, ...] = ("CPUExecutionProvider",)
    topn: int = 64
    min_weight: float = 1e-6
    normalize: bool = False
    format: Literal["string", "map"] = "string"


@dataclass(frozen=True, slots=True)
class SpladeSettings:
    """SPLADE runtime configuration for artifacts, encoding, and indexing.

    Attributes
    ----------
    model_id : str
        HuggingFace model identifier for the SPLADE model (e.g.,
        "naver/splade-cocondenser-ensembledistil").
    model_dir : Path
        Directory path containing the SPLADE PyTorch model files.
    onnx_dir : Path
        Directory path containing ONNX model files for SPLADE encoding.
    onnx_file : str
        Filename of the ONNX model file within onnx_dir.
    vectors_dir : Path
        Directory path for storing SPLADE vector embeddings (JsonVectorCollection
        shards).
    index_dir : Path
        Directory path for the SPLADE Lucene impact index.
    provider : str
        Device provider for SPLADE encoding (e.g., "cpu", "cuda").
    quantization : int
        Quantization level for model weights (typically 100 for int8 quantization).
    max_terms : int
        Maximum number of terms in SPLADE representations. Must be positive.
    max_clause_count : int
        Maximum number of clauses in Lucene boolean queries. Must be at least 1024.
    batch_size : int
        Batch size for SPLADE encoding operations. Must be positive.
    threads : int
        Number of threads for parallel SPLADE processing. Must be positive.
    enabled : bool
        Whether SPLADE retrieval is enabled. If False, SPLADE operations are skipped.
    max_query_terms : int
        Maximum number of terms to extract from queries. Must be non-negative.
    prune_below : float
        Minimum token weight threshold for pruning SPLADE tokens. Tokens below
        this threshold are discarded. Must be non-negative.
    analyzer : Literal["wordpiece", "code"]
        Tokenizer analyzer type. "wordpiece" uses standard WordPiece tokenization,
        "code" uses code-specific tokenization.
    static_prune_pct : float
        Static pruning percentage for SPLADE tokens (0.0 to 1.0). Tokens are
        pruned based on this percentage before max_query_terms filtering.
    onnx_query : SpladeOnnxQueryConfig | None, optional
        Optional ONNX query encoder configuration. If None, uses PyTorch model
        for query encoding. Defaults to None.
    """

    model_id: str
    model_dir: Path
    onnx_dir: Path
    onnx_file: str
    vectors_dir: Path
    index_dir: Path
    provider: str
    quantization: int
    max_terms: int
    max_clause_count: int
    batch_size: int
    threads: int
    enabled: bool
    max_query_terms: int
    prune_below: float
    analyzer: Literal["wordpiece", "code"]
    static_prune_pct: float
    onnx_query: SpladeOnnxQueryConfig | None = None


@dataclass(frozen=True, slots=True)
class XTRSettings:
    """XTR token-level index configuration.

    Attributes
    ----------
    model_id : str, optional
        HuggingFace model identifier for the XTR model. Defaults to
        "nomic-ai/CodeRankEmbed".
    device : str, optional
        Device for XTR model execution (e.g., "cuda", "cpu", "mps"). Defaults
        to "cuda".
    max_query_tokens : int, optional
        Maximum number of tokens in query text. Longer queries are truncated.
        Must be positive. Defaults to 256.
    candidate_k : int, optional
        Number of candidate documents to retrieve before XTR rescoring. Must
        be positive. Defaults to 200.
    dim : int, optional
        Embedding dimension for XTR token vectors. Must be positive. Defaults
        to 768.
    dtype : Literal["float16", "float32"], optional
        Data type for XTR token embeddings. "float16" reduces memory usage but
        may have lower precision. Defaults to "float16".
    enable : bool, optional
        Whether XTR retrieval is enabled. If False, XTR operations are skipped.
        Defaults to False.
    mode : Literal["narrow", "wide"], optional
        XTR search mode. "narrow" uses token-level matching, "wide" uses
        document-level matching. Defaults to "narrow".
    """

    model_id: str = "nomic-ai/CodeRankEmbed"
    device: str = "cuda"
    max_query_tokens: int = 256
    candidate_k: int = 200
    dim: int = 768
    dtype: Literal["float16", "float32"] = "float16"
    enable: bool = False
    mode: Literal["narrow", "wide"] = "narrow"


@dataclass(frozen=True, slots=True)
class BM25Settings:
    """BM25 configuration for corpus preparation and Lucene index tuning.

    Attributes
    ----------
    corpus_json_dir : Path
        Directory path containing JSONL corpus files for BM25 indexing. Each
        file should contain documents with "id", "title", "section", and "body"
        fields.
    index_dir : Path
        Directory path where the BM25 Lucene index will be built or loaded from.
    threads : int, optional
        Number of threads for BM25 index building and search operations. Must
        be positive. Defaults to 8.
    enabled : bool, optional
        Whether BM25 retrieval is enabled. If False, BM25 operations are skipped.
        Defaults to True.
    k1 : float, optional
        BM25 term frequency saturation parameter. Controls how quickly term
        frequency saturates. Must be positive. Defaults to 0.9.
    b : float, optional
        BM25 length normalization parameter. Controls the impact of document
        length on scoring. Must be non-negative. Defaults to 0.4.
    rm3_enabled : bool, optional
        Whether to enable RM3 (Relevance Model 3) query expansion. RM3 expands
        queries with relevant terms from top-ranked documents. Defaults to False.
    rm3_fb_docs : int, optional
        Number of feedback documents to use for RM3 expansion. Must be positive.
        Defaults to 10.
    rm3_fb_terms : int, optional
        Number of feedback terms to add to the query in RM3 expansion. Must be
        positive. Defaults to 10.
    rm3_original_query_weight : float, optional
        Weight for the original query terms in RM3 expansion (0.0 to 1.0).
        Higher values preserve more of the original query. Defaults to 0.5.
    analyzer : Literal["code", "standard"], optional
        Tokenizer analyzer type. "code" uses code-specific tokenization,
        "standard" uses standard text tokenization. Defaults to "code".
    stopwords : tuple[str, ...], optional
        Tuple of stopwords to filter during indexing and search. Empty tuple
        means no stopword filtering. Defaults to empty tuple.
    """

    corpus_json_dir: Path
    index_dir: Path
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


@dataclass(frozen=True, slots=True)
class EmbeddingsSettings:
    """Embedding provider configuration shared by CLIs and services.

    Attributes
    ----------
    provider : Literal["vllm", "hf"], optional
        Embedding provider backend. "vllm" uses vLLM for in-process or HTTP
        embedding generation. "hf" uses HuggingFace transformers directly.
        Defaults to "vllm".
    model_name : str, optional
        Model identifier for embedding generation (e.g., "nomic-ai/nomic-embed-code").
        Must be compatible with the selected provider. Defaults to
        "nomic-ai/nomic-embed-code".
    device : str, optional
        Device for embedding computation (e.g., "auto", "cuda", "cpu", "mps").
        "auto" selects the best available device. Defaults to "auto".
    batch_size : int, optional
        Batch size for embedding generation. Larger batches improve throughput
        but require more memory. Must be positive. Defaults to 64.
    micro_batch_size : int, optional
        Micro-batch size for batching multiple requests. Used for request
        coalescing in async scenarios. Must be positive. Defaults to 32.
    normalize : bool, optional
        Whether to L2-normalize embeddings to unit length. Normalized embeddings
        enable cosine similarity via dot product. Defaults to True.
    max_tokens : int, optional
        Maximum number of tokens per input text. Longer texts are truncated.
        Must be positive. Defaults to 4096.
    max_sequence_chars : int, optional
        Maximum number of characters per input sequence. Used for input validation
        and truncation. Must be positive. Defaults to 8192.
    retry_max_attempts : int, optional
        Maximum number of retry attempts for failed embedding requests. Must be
        non-negative. Defaults to 3.
    retry_backoff_ms : int, optional
        Backoff delay in milliseconds between retry attempts. Must be non-negative.
        Defaults to 250.
    max_pending_batches : int, optional
        Maximum number of pending batches in the embedding queue. Used for
        backpressure control. Must be non-negative. Defaults to 8.
    max_wait_ms : int, optional
        Maximum wait time in milliseconds before emitting a partial batch.
        Used for latency control in batching systems. Must be non-negative.
        Defaults to 8.
    allow_hf_fallback : bool, optional
        Whether to allow fallback to HuggingFace transformers when vLLM is
        unavailable. Defaults to True.
    """

    provider: Literal["vllm", "hf"] = "vllm"
    model_name: str = "nomic-ai/nomic-embed-code"
    device: str = "auto"
    batch_size: int = 64
    micro_batch_size: int = 32
    normalize: bool = True
    max_tokens: int = 4096
    max_sequence_chars: int = 8192
    retry_max_attempts: int = 3
    retry_backoff_ms: int = 250
    max_pending_batches: int = 8
    max_wait_ms: int = 8
    allow_hf_fallback: bool = True


@dataclass(frozen=True, slots=True)
class VLLMSettings:
    """Configuration for the vLLM embedding service.

    Attributes
    ----------
    base_url : str, optional
        Base URL for vLLM HTTP API when run_mode is "http". Format:
        "http://host:port/v1". Defaults to "http://127.0.0.1:8001/v1".
    model : str, optional
        Model identifier for vLLM (e.g., "nomic-ai/nomic-embed-code"). Must be
        compatible with vLLM's embedding API. Defaults to "nomic-ai/nomic-embed-code".
    batch_size : int, optional
        Batch size for vLLM embedding requests. Larger batches improve throughput
        but require more memory. Must be positive. Defaults to 64.
    embedding_dim : int, optional
        Expected embedding dimension from the model. Used for validation and
        array allocation. Must be positive. Defaults to 3584.
    timeout_s : float, optional
        Request timeout in seconds for vLLM HTTP requests. Must be positive.
        Defaults to 120.0.
    run_mode : Literal["inprocess", "http"], optional
        vLLM execution mode. "inprocess" runs vLLM in the same process,
        "http" uses a separate HTTP server. Defaults to "inprocess".
    memory_utilization : float, optional
        Memory utilization target for vLLM (0.0 to 1.0). Higher values use more
        GPU memory but may cause OOM errors. Defaults to 0.92.
    max_num_batched_tokens : int, optional
        Maximum number of tokens in a single batch. Used for memory management.
        Must be positive. Defaults to 65_536.
    normalize : bool, optional
        Whether to L2-normalize embeddings to unit length. Defaults to True.
    embedding_mode : Literal["LAST", "CLS", "MEAN"], optional
        Pooling strategy for generating embeddings from token vectors. "LAST"
        uses the last token, "CLS" uses the [CLS] token, "MEAN" averages all
        tokens. Defaults to "LAST".
    max_concurrent_requests : int, optional
        Maximum number of concurrent requests to vLLM HTTP API. Used for
        connection pooling. Must be positive. Defaults to 4.
    task : Literal["embed"] | None, optional
        Deprecated: Use embedding_mode instead. Task type for vLLM. Defaults to None.
    """

    base_url: str = "http://127.0.0.1:8001/v1"
    model: str = "nomic-ai/nomic-embed-code"
    batch_size: int = 64
    embedding_dim: int = 3584
    timeout_s: float = 120.0
    run_mode: Literal["inprocess", "http"] = "inprocess"
    memory_utilization: float = 0.92
    max_num_batched_tokens: int = 65_536
    normalize: bool = True
    embedding_mode: Literal["LAST", "CLS", "MEAN"] = "LAST"
    max_concurrent_requests: int = 4
    task: Literal["embed"] | None = None

    def resolved_embedding_mode(self) -> Literal["LAST", "CLS", "MEAN"]:
        """Return embedding mode while handling deprecated ``task`` flag.

        Returns
        -------
        Literal["LAST", "CLS", "MEAN"]
            The embedding mode to use. Emits a deprecation warning if the
            deprecated task field is set, then returns the embedding_mode value.
        """
        if self.task:
            warnings.warn(
                "VLLMSettings.task is deprecated; use embedding_mode instead",
                DeprecationWarning,
                stacklevel=2,
            )
        return self.embedding_mode

    @property
    def pooling_type(self) -> Literal["LAST", "CLS", "MEAN"]:
        """Return literal pooling type for compatibility helpers."""
        return self.resolved_embedding_mode()

    def pooler_kwargs(self) -> dict[str, object]:
        """Return keyword arguments for vLLM PoolerConfig construction.

        Returns
        -------
        dict[str, object]
            Dictionary containing pooling_type and normalize keys suitable
            for passing to vLLM PoolerConfig constructor.
        """
        return {
            "pooling_type": self.pooling_type,
            "normalize": self.normalize,
        }


@dataclass(frozen=True, slots=True)
class CodeRankSettings:
    """Dense CodeRank retriever configuration."""

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


@dataclass(frozen=True, slots=True)
class CodeRankLLMSettings:
    """Configuration for the CodeRank listwise reranker."""

    model_id: str = "nomic-ai/CodeRankLLM"
    device: str = "cpu"
    max_new_tokens: int = 256
    temperature: float = 0.0
    top_p: float = 1.0
    enabled: bool = False
    budget_ms: int = 300


@dataclass(frozen=True, slots=True)
class WarpSettings:
    """WARP/XTR late-interaction configuration."""

    index_dir: Path = Path("indexes/warp_xtr")
    model_id: str = "intfloat/e5-multivector-large"
    device: str = "cpu"
    top_k: int = 200
    enabled: bool = False
    budget_ms: int = 180


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Top-level immutable configuration.

    Attributes
    ----------
    version : str
        Configuration API version string (e.g., "1.0"). Used for version
        compatibility checking.
    paths : PathsConfig
        Filesystem paths configuration for all application directories.
    duckdb : DuckDBSettings
        DuckDB database configuration and connection settings.
    faiss : FAISSSettings
        FAISS vector index configuration and search parameters.
    bm25 : BM25Settings
        BM25 sparse retrieval configuration and index settings.
    splade : SpladeSettings
        SPLADE sparse retrieval configuration and model settings.
    xtr : XTRSettings
        XTR token-level retrieval configuration and model settings.
    index : IndexSettings
        Combined FAISS/BM25/SPLADE/hybrid tuning knobs for indexing and search.
    embeddings : EmbeddingsSettings
        Embedding provider configuration shared across CLIs and services.
    vllm : VLLMSettings
        vLLM embedding service configuration and runtime settings.
    search : SearchSettings
        Hybrid search weighting and Stage-0 tuning configuration. Defaults to
        SearchSettings() with default values.
    limits : ServerLimits
        Server resource limits including max results and rate limiting configuration.
        Defaults to ServerLimits() with default values.
    redis : RedisSettings
        Redis connection and L1/L2 cache configuration. Defaults to RedisSettings()
        with default values.
    rerank : RerankSettings
        Late-interaction reranker configuration. Defaults to RerankSettings() with
        default values.
    coderank : CodeRankSettings
        Dense retriever configuration for CodeRank operations. Defaults to
        CodeRankSettings() with default values.
    coderank_llm : CodeRankLLMSettings
        Listwise reranker configuration for CodeRank LLM. Defaults to
        CodeRankLLMSettings() with default values.
    warp : WarpSettings
        WARP/XTR reranker configuration. Defaults to WarpSettings() with default
        values.
    logging : LoggingSettings
        Logging output configuration. Defaults to LoggingSettings() with default
        values.
    eval : EvalSettings
        Evaluation settings configuration. Defaults to EvalSettings() with default
        values.
    extras : Mapping[str, object]
        Additional configuration key-value pairs for extensibility. Defaults to
        empty dictionary.
    """

    version: str
    paths: PathsConfig
    duckdb: DuckDBSettings
    faiss: FAISSSettings
    bm25: BM25Settings
    splade: SpladeSettings
    xtr: XTRSettings
    index: IndexSettings
    embeddings: EmbeddingsSettings
    vllm: VLLMSettings
    search: SearchSettings = field(default_factory=SearchSettings)
    limits: ServerLimits = field(default_factory=ServerLimits)
    redis: RedisSettings = field(default_factory=RedisSettings)
    rerank: RerankSettings = field(default_factory=RerankSettings)
    coderank: CodeRankSettings = field(default_factory=CodeRankSettings)
    coderank_llm: CodeRankLLMSettings = field(default_factory=CodeRankLLMSettings)
    warp: WarpSettings = field(default_factory=WarpSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
    eval: EvalSettings = field(default_factory=EvalSettings)
    extras: Mapping[str, object] = field(default_factory=dict)


def is_compatible_version(version: str) -> bool:
    """Return True if ``version`` matches the current major version.

    Parameters
    ----------
    version : str
        Version string to evaluate.

    Returns
    -------
    bool
        ``True`` when the provided version shares the same major number.
    """
    return (version or "").split(".", 1)[0] == CONFIG_API_VERSION.split(".", 1)[0]


def validate_config(cfg: AppConfig) -> None:
    """Validate the supplied configuration or raise ValueError.

    Parameters
    ----------
    cfg : AppConfig
        Configuration instance to validate.

    Notes
    -----
    This function validates configuration invariants by calling various
    validation functions. If any validation fails, ValueError is raised
    via the :func:`_require` helper function.
    """
    _validate_version(cfg)
    _validate_faiss_settings(cfg.faiss)
    _validate_search_settings(cfg.search)
    _validate_bm25_settings(cfg.bm25)
    _validate_embeddings_settings(cfg.embeddings)
    _validate_vllm_settings(cfg.vllm)
    _validate_xtr_settings(cfg.xtr)
    _validate_eval_settings(cfg.eval)
    _validate_index_settings(cfg.index)


def _validate_version(cfg: AppConfig) -> None:
    if not is_compatible_version(cfg.version):
        msg = f"Incompatible config version {cfg.version!r}; expected {CONFIG_API_VERSION}"
        raise ValueError(msg)


def _validate_faiss_settings(faiss: FAISSSettings) -> None:
    _require("faiss.default_k must be positive", condition=faiss.default_k > 0)
    _require("faiss.default_nprobe must be positive", condition=faiss.default_nprobe > 0)
    _require("faiss.refine_k_factor must be positive", condition=faiss.refine_k_factor > 0)


def _validate_search_settings(search: SearchSettings) -> None:
    _require("search.max_results must be positive", condition=search.max_results > 0)
    _require("search.per_channel_k must be positive", condition=search.per_channel_k > 0)
    _require("search.fusion_k must be positive", condition=search.fusion_k > 0)
    _require("search.rrf_base must be positive", condition=search.rrf_base > 0)


def _validate_bm25_settings(bm25: BM25Settings) -> None:
    _require("bm25.threads must be positive", condition=bm25.threads > 0)
    _require("bm25.k1 must be positive", condition=bm25.k1 > 0)
    _require("bm25.b must be non-negative", condition=bm25.b >= 0)
    _require("bm25.rm3_fb_docs must be positive", condition=bm25.rm3_fb_docs > 0)
    _require("bm25.rm3_fb_terms must be positive", condition=bm25.rm3_fb_terms > 0)


def _validate_embeddings_settings(embeddings: EmbeddingsSettings) -> None:
    _require("embeddings.batch_size must be positive", condition=embeddings.batch_size > 0)
    _require(
        "embeddings.micro_batch_size must be positive",
        condition=embeddings.micro_batch_size > 0,
    )
    _require("embeddings.max_tokens must be positive", condition=embeddings.max_tokens > 0)
    _require(
        "embeddings.max_sequence_chars must be positive",
        condition=embeddings.max_sequence_chars > 0,
    )
    _require(
        "embeddings.retry_max_attempts must be non-negative",
        condition=embeddings.retry_max_attempts >= 0,
    )
    _require(
        "embeddings.retry_backoff_ms must be non-negative",
        condition=embeddings.retry_backoff_ms >= 0,
    )
    _require(
        "embeddings.max_pending_batches must be non-negative",
        condition=embeddings.max_pending_batches >= 0,
    )
    _require(
        "embeddings.max_wait_ms must be non-negative",
        condition=embeddings.max_wait_ms >= 0,
    )


def _validate_vllm_settings(vllm: VLLMSettings) -> None:
    _require("vllm.batch_size must be positive", condition=vllm.batch_size > 0)
    _require("vllm.embedding_dim must be positive", condition=vllm.embedding_dim > 0)
    _require("vllm.timeout_s must be positive", condition=vllm.timeout_s > 0)
    _require(
        "vllm.max_num_batched_tokens must be positive",
        condition=vllm.max_num_batched_tokens > 0,
    )
    _require(
        "vllm.max_concurrent_requests must be positive",
        condition=vllm.max_concurrent_requests > 0,
    )


def _validate_xtr_settings(xtr: XTRSettings) -> None:
    _require("xtr.dim must be positive", condition=xtr.dim > 0)
    _require("xtr.max_query_tokens must be positive", condition=xtr.max_query_tokens > 0)
    _require("xtr.candidate_k must be positive", condition=xtr.candidate_k > 0)


def _validate_eval_settings(eval_cfg: EvalSettings) -> None:
    _require("eval.oracle_top_k must be positive", condition=eval_cfg.oracle_top_k > 0)
    if eval_cfg.max_queries is not None:
        _require("eval.max_queries must be positive", condition=eval_cfg.max_queries > 0)
    for value in eval_cfg.k_values:
        _require("eval.k_values entries must be positive", condition=value > 0)


def _validate_index_settings(index_cfg: IndexSettings) -> None:
    _require("index.vec_dim must be positive", condition=index_cfg.vec_dim > 0)
    _require("index.chunk_budget must be positive", condition=index_cfg.chunk_budget > 0)
    _require("index.faiss_nlist must be positive", condition=index_cfg.faiss_nlist > 0)
    _require("index.faiss_nprobe must be positive", condition=index_cfg.faiss_nprobe > 0)
    _require("index.nlist must be positive", condition=(index_cfg.nlist or 0) > 0)
    _require(
        "index.default_nprobe must be positive",
        condition=(index_cfg.default_nprobe or 0) > 0,
    )
    _require("index.default_k must be positive", condition=index_cfg.default_k > 0)
    _require("index.rrf_k must be positive", condition=index_cfg.rrf_k > 0)
    _require(
        "index.hybrid_top_k_per_channel must be positive",
        condition=index_cfg.hybrid_top_k_per_channel > 0,
    )
    _require("index.preview_max_chars must be positive", condition=index_cfg.preview_max_chars > 0)
    _require("index.pq_m must be positive", condition=index_cfg.pq_m > 0)
    _require("index.pq_nbits must be positive", condition=index_cfg.pq_nbits > 0)
    _require("index.hnsw_m must be positive", condition=index_cfg.hnsw_m > 0)
    _require(
        "index.hnsw_ef_construction must be positive",
        condition=index_cfg.hnsw_ef_construction > 0,
    )
    _require("index.hnsw_ef_search must be positive", condition=index_cfg.hnsw_ef_search > 0)
    _require("index.refine_k_factor must be positive", condition=index_cfg.refine_k_factor > 0)
    _require(
        "index.recency_half_life_days must be positive",
        condition=(not index_cfg.recency_enabled or index_cfg.recency_half_life_days > 0),
    )
    _require(
        "index.recency_max_boost must be non-negative",
        condition=index_cfg.recency_max_boost >= 0,
    )
