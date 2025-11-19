"""Load application configuration from environment variables and optional files."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, TypeVar, cast

from codeintel_rev.config.api import (
    CONFIG_API_VERSION,
    AppConfig,
    BM25Settings,
    DuckDBSettings,
    EmbeddingsSettings,
    EvalSettings,
    FAISSSettings,
    IndexSettings,
    LoggingSettings,
    PathsConfig,
    PRFSettings,
    SearchSettings,
    SpladeOnnxQueryConfig,
    SpladeSettings,
    VLLMSettings,
    XTRSettings,
    validate_config,
)
from codeintel_rev.runtime.imports import gate_import

LookupFn = Callable[[str, object], object]
_MappingValue = TypeVar("_MappingValue", int, float)
_DEFAULT_RRF_WEIGHTS: Final[dict[str, float]] = {
    "semantic": 1.0,
    "bm25": 1.0,
    "splade": 1.0,
    "warp": 1.1,
}
_DEFAULT_PREFETCH: Final[dict[str, int]] = {"semantic": 200, "bm25": 200, "splade": 200}


def _to_bool(value: str | None, *, default: bool = False) -> bool:
    """Convert a string value to boolean with flexible parsing.

    Parameters
    ----------
    value : str | None
        String value to convert. Can be None or empty.
    default : bool, optional
        Default value to return if the string cannot be parsed as a boolean.
        Defaults to False.

    Returns
    -------
    bool
        True if value matches "1", "true", "yes", "y", or "on" (case-insensitive).
        False if value matches "0", "false", "no", "n", or "off" (case-insensitive).
        Returns default if value is None, empty, or doesn't match any pattern.
    """
    normalized = (value or "").strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _coerce_int(value: object, *, default: int) -> int:
    """Coerce a value to an integer, returning default on failure.

    Parameters
    ----------
    value : object
        Value to convert to integer. Can be any type that can be converted
        via str() and then int().
    default : int
        Default value to return if conversion fails or value is empty.

    Returns
    -------
    int
        Integer representation of the value, or default if conversion fails
        due to AttributeError, TypeError, ValueError, or empty string.
    """
    try:
        text = str(value).strip()
    except (AttributeError, TypeError, ValueError):
        return default
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        return default


def _optional_int(value: object | None) -> int | None:
    """Return integer for value or None if parsing fails/absent.

    Returns
    -------
    int | None
        Parsed integer value, or None if value is None, empty, or cannot be
        parsed as an integer.
    """
    if value is None:
        return None
    try:
        text = str(value).strip()
    except (AttributeError, TypeError, ValueError):
        return None
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _parse_int_list(value: object, default: tuple[int, ...]) -> tuple[int, ...]:
    """Parse a comma-delimited list of integers.

    Parameters
    ----------
    value : object
        Value to parse. Should be a string containing comma-delimited integers.
    default : tuple[int, ...]
        Default value to return if parsing fails or value is empty.

    Returns
    -------
    tuple[int, ...]
        Tuple of parsed integers, or default if parsing fails or value is empty.
    """
    try:
        text = str(value).strip()
    except (AttributeError, TypeError, ValueError):
        return default
    if not text:
        return default
    parts = [part.strip() for part in text.split(",") if part.strip()]
    parsed: list[int] = []
    for part in parts:
        try:
            parsed.append(int(part))
        except ValueError:
            continue
    return tuple(parsed) if parsed else default


def _parse_mapping(
    value: object,
    *,
    default: Mapping[str, _MappingValue],
    coerce: Callable[[object], _MappingValue],
) -> dict[str, _MappingValue]:
    """Parse a JSON or mapping value into a ``str -> number`` dictionary.

    Parameters
    ----------
    value : object
        Value to parse. Can be a Mapping, JSON string, or other object.
    default : Mapping[str, _MappingValue]
        Default mapping to return if parsing fails or value is empty.
    coerce : Callable[[object], _MappingValue]
        Function to coerce individual values to the target type.

    Returns
    -------
    dict[str, _MappingValue]
        Dictionary mapping string keys to coerced values, or default if parsing fails.
    """
    if isinstance(value, Mapping):
        parsed: dict[str, _MappingValue] = {}
        for key, mapping_value in value.items():
            try:
                parsed[str(key)] = coerce(mapping_value)
            except (TypeError, ValueError):
                continue
        return parsed or dict(default)
    text = _as_optional_str(value)
    if not text:
        return dict(default)
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return dict(default)
    if isinstance(payload, Mapping):
        parsed_payload: dict[str, _MappingValue] = {}
        for key, mapping_value in payload.items():
            try:
                parsed_payload[str(key)] = coerce(mapping_value)
            except (TypeError, ValueError):
                continue
        return parsed_payload or dict(default)
    return dict(default)


def _parse_float_mapping(value: object, *, default: Mapping[str, float]) -> dict[str, float]:
    """Return mapping of floats using :func:`_parse_mapping`.

    Parameters
    ----------
    value : object
        Value to parse. Can be a Mapping, JSON string, or other object.
    default : Mapping[str, float]
        Default mapping to return if parsing fails or value is empty.

    Returns
    -------
    dict[str, float]
        Dictionary mapping string keys to float values, or default if parsing fails.
    """
    return _parse_mapping(value, default=default, coerce=lambda raw: float(raw))


def _parse_int_mapping(value: object, *, default: Mapping[str, int]) -> dict[str, int]:
    """Return mapping of ints using :func:`_parse_mapping`.

    Parameters
    ----------
    value : object
        Value to parse. Can be a Mapping, JSON string, or other object.
    default : Mapping[str, int]
        Default mapping to return if parsing fails or value is empty.

    Returns
    -------
    dict[str, int]
        Dictionary mapping string keys to int values, or default if parsing fails.
    """
    return _parse_mapping(value, default=default, coerce=lambda raw: int(raw))


def _coerce_float(value: object, *, default: float) -> float:
    """Coerce a value to a float, returning default on failure.

    Parameters
    ----------
    value : object
        Value to convert to float. Can be any type that can be converted
        via str() and then float().
    default : float
        Default value to return if conversion fails or value is empty.

    Returns
    -------
    float
        Float representation of the value, or default if conversion fails
        due to AttributeError, TypeError, ValueError, or empty string.
    """
    try:
        text = str(value).strip()
    except (AttributeError, TypeError, ValueError):
        return default
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _parse_int_with_suffix(value: object, default: int) -> int:
    """Parse integer strings that may include k-style suffixes.

    Parameters
    ----------
    value : object
        Value to parse. Can be any type convertible to string. Supports
        "k" suffix (e.g., "64k" becomes 64000) and underscores for readability.
    default : int
        Default value to return if parsing fails or value is empty.

    Returns
    -------
    int
        Parsed integer value. If the string ends with "k", multiplies the
        numeric portion by 1000. Returns default if conversion fails due to
        AttributeError, TypeError, ValueError, or empty string.
    """
    try:
        text = str(value).strip().lower().replace("_", "")
    except (AttributeError, TypeError, ValueError):
        return default
    if not text:
        return default
    try:
        if text.endswith("k"):
            return int(float(text[:-1]) * 1000)
        return int(text)
    except ValueError:
        return default


def _load_file(path: Path) -> Mapping[str, object]:
    """Load configuration data from a YAML or JSON file.

    Parameters
    ----------
    path : Path
        Path to the configuration file. Supports .yml, .yaml, and .json extensions.

    Returns
    -------
    Mapping[str, object]
        Dictionary containing parsed configuration data. Returns empty dict
        if the file doesn't exist, has unsupported extension, or contains
        non-mapping data.

    Raises
    ------
    ImportError
        If the file is YAML but yaml.safe_load is not available.

    Notes
    -----
    This function calls json.load() which may raise json.JSONDecodeError
    if the file contains invalid JSON syntax. The exception is propagated
    to the caller.
    """
    if not path.exists():
        return {}
    suffix = path.suffix.lower()
    if suffix in {".yml", ".yaml"}:
        yaml_mod = gate_import("yaml", "parse YAML configuration files")
        safe_load = getattr(yaml_mod, "safe_load", None)
        if safe_load is None:
            message = "yaml.safe_load is not available"
            raise ImportError(message)
        with path.open("r", encoding="utf-8") as handle:
            data = safe_load(handle)
        if isinstance(data, Mapping):
            return cast("Mapping[str, object]", data)
        return {}
    if suffix == ".json":
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, Mapping):
            return cast("Mapping[str, object]", data)
        return {}
    return {}


def _as_path(value: str | Path) -> Path:
    """Convert a value to an absolute Path with user expansion.

    Parameters
    ----------
    value : str | Path
        Path value to convert. Can be a string or Path object.

    Returns
    -------
    Path
        Absolute resolved path with user home directory expanded (~).
        Uses resolve(strict=False) so missing paths don't raise errors.
    """
    return Path(value).expanduser().resolve(strict=False)


def _optional_path(value: object) -> Path | None:
    """Convert a value to Path if it's a non-empty string or Path, else None.

    Parameters
    ----------
    value : object
        Value to convert. Can be None, empty string, str, or Path.

    Returns
    -------
    Path | None
        Path object if value is a non-empty string or Path, None otherwise.
    """
    if isinstance(value, (str, Path)) and value:
        return _as_path(value)
    return None


def _resolve_repo_path(paths: PathsConfig, value: Path) -> Path:
    """Resolve a path relative to the repository root if not absolute.

    Parameters
    ----------
    paths : PathsConfig
        Paths configuration containing the repository root.
    value : Path
        Path to resolve. If absolute, returned as-is. If relative, resolved
        relative to paths.repo_root.

    Returns
    -------
    Path
        Absolute resolved path with user expansion. Relative paths are
        resolved relative to the repository root.
    """
    candidate = value
    if not candidate.is_absolute():
        candidate = paths.repo_root / candidate
    return candidate.expanduser().resolve(strict=False)


def _repo_path(paths: PathsConfig, raw_value: object, *, default: Path) -> Path:
    """Resolve a repository-relative path with fallback to default.

    Parameters
    ----------
    paths : PathsConfig
        Paths configuration containing the repository root.
    raw_value : object
        Raw value to convert to Path. Can be Path, non-empty str, or other types.
    default : Path
        Default path to use if raw_value is None, empty, or cannot be converted.

    Returns
    -------
    Path
        Absolute resolved path. If raw_value is a valid Path or non-empty string,
        it's resolved relative to the repository root. Otherwise, default is used.
    """
    candidate: Path | None = None
    if isinstance(raw_value, Path):
        candidate = raw_value
    elif isinstance(raw_value, str):
        text = raw_value.strip()
        if text:
            candidate = Path(text)
    if candidate is None:
        candidate = default
    return _resolve_repo_path(paths, candidate)


def _optional_repo_path(paths: PathsConfig, raw_value: object | None) -> Path | None:
    """Resolve an optional repository-relative path.

    Parameters
    ----------
    paths : PathsConfig
        Paths configuration containing the repository root.
    raw_value : object | None
        Raw value to convert to Path. Can be None, Path, or string.

    Returns
    -------
    Path | None
        Absolute resolved path if raw_value is a valid non-empty Path or string,
        None if raw_value is None or empty.
    """
    if raw_value is None:
        return None
    if isinstance(raw_value, Path):
        candidate = raw_value
    else:
        text = str(raw_value).strip()
        if not text:
            return None
        candidate = Path(text)
    return _resolve_repo_path(paths, candidate)


def _as_str(value: object) -> str:
    """Convert a value to string.

    Parameters
    ----------
    value : object
        Value to convert to string via str().

    Returns
    -------
    str
        String representation of the value.
    """
    return str(value)


def _as_optional_str(value: object) -> str | None:
    """Convert a value to string, returning None for None input.

    Parameters
    ----------
    value : object
        Value to convert to string. Can be None.

    Returns
    -------
    str | None
        String representation of the value, or None if value is None.
    """
    if value is None:
        return None
    return str(value)


def _build_lookup(env: Mapping[str, str], file_data: Mapping[str, object]) -> LookupFn:
    """Build a lookup function that checks environment variables then file data.

    Parameters
    ----------
    env : Mapping[str, str]
        Environment variable mapping (typically os.environ).
    file_data : Mapping[str, object]
        Configuration data loaded from YAML/JSON files.

    Returns
    -------
    LookupFn
        A callable that looks up values by name, checking environment variables
        first, then file data, then returning a default if not found.

    Notes
    -----
    Environment variables take precedence over file data. The returned function
    signature is (name: str, default: object) -> object.
    """

    def _get(name: str, default: object) -> object:
        """Look up a configuration value by name.

        Parameters
        ----------
        name : str
            Configuration key name to look up.
        default : object
            Default value to return if name is not found in env or file_data.

        Returns
        -------
        object
            Value from environment if present, otherwise value from file_data,
            otherwise default.
        """
        if name in env:
            return env[name]
        if name in file_data:
            return file_data[name]
        return default

    return _get


def _paths_config(get: LookupFn) -> PathsConfig:
    """Build PathsConfig from lookup function with defaults.

    Parameters
    ----------
    get : LookupFn
        Lookup function that retrieves configuration values by name.

    Returns
    -------
    PathsConfig
        Paths configuration with repository root, data directory, cache directory,
        and logs directory resolved from environment variables or defaults.
    """
    repo_root = _as_path(_as_str(get("BASE_DIR", Path.cwd())))
    data_dir = _as_path(_as_str(get("DATA_DIR", repo_root / "data")))
    cache_dir = _as_path(_as_str(get("CACHE_DIR", repo_root / ".cache")))
    logs_dir = _as_path(_as_str(get("LOGS_DIR", repo_root / "logs")))
    return PathsConfig(
        repo_root=repo_root, data_dir=data_dir, cache_dir=cache_dir, logs_dir=logs_dir
    )


def _duckdb_settings(get: LookupFn, data_dir: Path) -> DuckDBSettings:
    """Build DuckDBSettings from lookup function with defaults.

    Parameters
    ----------
    get : LookupFn
        Lookup function that retrieves configuration values by name.
    data_dir : Path
        Default data directory used for database path if not specified.

    Returns
    -------
    DuckDBSettings
        DuckDB configuration with database path, thread count, object cache
        setting, temporary directory, and connection pool size.
    """
    database = _as_path(_as_str(get("DUCKDB_DATABASE", data_dir / "catalog.duckdb")))
    threads = _coerce_int(get("DUCKDB_THREADS", ""), default=0) or None
    object_cache = _to_bool(_as_optional_str(get("DUCKDB_OBJECT_CACHE", "true")), default=True)
    temp_directory = _optional_path(get("DUCKDB_TEMP_DIR", None))
    pool_size = _coerce_int(get("DUCKDB_POOL_SIZE", "4"), default=4)
    return DuckDBSettings(
        database=database,
        threads=threads,
        object_cache=object_cache,
        temp_directory=temp_directory,
        pool_size=pool_size,
    )


def _faiss_settings(get: LookupFn, data_dir: Path) -> FAISSSettings:
    """Build FAISSSettings from lookup function with defaults.

    Parameters
    ----------
    get : LookupFn
        Lookup function that retrieves configuration values by name.
    data_dir : Path
        Default data directory used for index path if not specified.

    Returns
    -------
    FAISSSettings
        FAISS configuration with index path, default k (number of results),
        default nprobe (number of clusters to search), and refine k factor.
    """
    index_path = _as_path(_as_str(get("FAISS_INDEX_PATH", data_dir / "faiss" / "primary.index")))
    default_k = _coerce_int(get("FAISS_DEFAULT_K", "50"), default=50)
    default_nprobe = _coerce_int(get("FAISS_DEFAULT_NPROBE", "64"), default=64)
    refine_k_factor = _coerce_float(get("FAISS_REFINE_K_FACTOR", "1.0"), default=1.0)
    return FAISSSettings(
        index_path=index_path,
        default_k=default_k,
        default_nprobe=default_nprobe,
        refine_k_factor=refine_k_factor,
    )


def _search_settings(get: LookupFn) -> SearchSettings:
    """Build SearchSettings from lookup function with defaults.

    Parameters
    ----------
    get : LookupFn
        Lookup function that retrieves configuration values by name.

    Returns
    -------
    SearchSettings
        Hybrid search configuration with channel weights (BM25, SPLADE, FAISS),
        per-channel k values, fusion k, RRF (Reciprocal Rank Fusion) base,
        and maximum results limit.
    """
    bm25_weight = _coerce_float(get("SEARCH_BM25_WEIGHT", "0.2"), default=0.2)
    splade_weight = _coerce_float(get("SEARCH_SPLADE_WEIGHT", "0.3"), default=0.3)
    faiss_weight = _coerce_float(get("SEARCH_FAISS_WEIGHT", "0.5"), default=0.5)
    per_channel_k = _coerce_int(get("SEARCH_PER_CHANNEL_K", "100"), default=100)
    fusion_k = _coerce_int(get("SEARCH_FUSION_K", "50"), default=50)
    rrf_base = _coerce_int(get("SEARCH_RRF_BASE", "60"), default=60)
    max_results = _coerce_int(get("SEARCH_MAX_RESULTS", "50"), default=50)
    return SearchSettings(
        bm25_weight=bm25_weight,
        splade_weight=splade_weight,
        faiss_weight=faiss_weight,
        per_channel_k=per_channel_k,
        fusion_k=fusion_k,
        rrf_base=rrf_base,
        max_results=max_results,
    )


def _logging_settings(get: LookupFn) -> LoggingSettings:
    """Build LoggingSettings from lookup function with defaults.

    Parameters
    ----------
    get : LookupFn
        Lookup function that retrieves configuration values by name.

    Returns
    -------
    LoggingSettings
        Logging configuration with log level and JSON output format flag.
    """
    level = _as_str(get("LOG_LEVEL", "INFO"))
    as_json = _to_bool(_as_optional_str(get("LOG_JSON", "false")), default=False)
    return LoggingSettings(level=level, json=as_json)


def _eval_settings(paths: PathsConfig, get: LookupFn) -> EvalSettings:
    """Build EvalSettings from lookup function with defaults.

    Parameters
    ----------
    paths : PathsConfig
        Filesystem paths configuration for resolving relative paths.
    get : LookupFn
        Lookup function that retrieves configuration values by name.

    Returns
    -------
    EvalSettings
        Evaluation settings with enabled flag, queries path, output directory,
        k values, max queries, oracle top-k, and XTR-as-oracle flag.
    """
    enabled = _to_bool(_as_optional_str(get("EVAL_ENABLED", "false")), default=False)
    queries_raw = _as_optional_str(get("EVAL_QUERIES_PATH", None))
    queries_path = _optional_repo_path(paths, queries_raw) if queries_raw else None
    default_output = paths.repo_root / "artifacts" / "eval"
    output_dir = _repo_path(paths, get("EVAL_OUTPUT_DIR", default_output), default=default_output)
    k_values = _parse_int_list(get("EVAL_K_VALUES", ""), (5, 10, 20))
    max_queries = _optional_int(get("EVAL_MAX_QUERIES", None))
    oracle_top_k = _coerce_int(get("EVAL_ORACLE_TOP_K", "50"), default=50)
    xtr_as_oracle = _to_bool(_as_optional_str(get("EVAL_XTR_AS_ORACLE", "false")), default=False)
    return EvalSettings(
        enabled=enabled,
        queries_path=queries_path,
        output_dir=output_dir,
        k_values=k_values,
        max_queries=max_queries,
        oracle_top_k=oracle_top_k,
        xtr_as_oracle=xtr_as_oracle,
    )


def _embeddings_settings(get: LookupFn) -> EmbeddingsSettings:
    """Build EmbeddingsSettings from lookup function with defaults.

    Parameters
    ----------
    get : LookupFn
        Lookup function that retrieves configuration values by name.

    Returns
    -------
    EmbeddingsSettings
        Embedding provider configuration with all fields populated from
        environment variables and file data, using defaults when values
        are not specified.
    """
    provider_env = _as_str(get("EMBED_PROVIDER", "vllm")).strip().lower()
    provider: Literal["vllm", "hf"] = "hf" if provider_env == "hf" else "vllm"
    model_name = _as_str(
        get(
            "EMBED_MODEL",
            get("VLLM_MODEL", "nomic-ai/nomic-embed-code"),
        )
    )
    batch_size = _coerce_int(get("EMBED_BATCH_SIZE", "64"), default=64)
    micro_default = str(min(max(batch_size // 2, 16), 64))
    micro_batch = _coerce_int(
        get("EMBED_MICRO_BATCH_SIZE", micro_default), default=int(micro_default)
    )
    normalize_flag = _as_optional_str(get("EMBED_NORMALIZE", None))
    if normalize_flag is None:
        normalize_flag = _as_optional_str(get("VLLM_NORMALIZE", "1"))
    normalize = (normalize_flag or "1").strip().lower() in {"1", "true", "yes"}
    max_tokens = _coerce_int(get("EMBED_MAX_TOKENS", "4096"), default=4096)
    max_chars = _coerce_int(get("EMBED_MAX_SEQUENCE_CHARS", "8192"), default=8192)
    retry_max = _coerce_int(get("EMBED_MAX_RETRIES", "3"), default=3)
    retry_backoff = _coerce_int(get("EMBED_RETRY_BACKOFF_MS", "250"), default=250)
    max_pending = _coerce_int(get("EMBED_MAX_PENDING_BATCHES", "8"), default=8)
    max_wait = _coerce_int(get("EMBED_MAX_WAIT_MS", "8"), default=8)
    allow_hf = _to_bool(_as_optional_str(get("EMBED_ALLOW_HF_FALLBACK", "true")), default=True)
    return EmbeddingsSettings(
        provider=provider,
        model_name=model_name,
        device=_as_str(get("EMBED_DEVICE", "auto")),
        batch_size=batch_size,
        micro_batch_size=micro_batch,
        normalize=normalize,
        max_tokens=max_tokens,
        max_sequence_chars=max_chars,
        retry_max_attempts=retry_max,
        retry_backoff_ms=retry_backoff,
        max_pending_batches=max_pending,
        max_wait_ms=max_wait,
        allow_hf_fallback=allow_hf,
    )


def _vllm_settings(get: LookupFn) -> VLLMSettings:
    """Build VLLMSettings from lookup function with defaults.

    Parameters
    ----------
    get : LookupFn
        Lookup function that retrieves configuration values by name.

    Returns
    -------
    VLLMSettings
        vLLM configuration with all fields populated from environment
        variables and file data, including run mode, embedding mode,
        pooling type, batch settings, and timeout configuration.
    """
    run_mode_env = _as_str(get("VLLM_RUN_MODE", "inprocess")).strip().lower()
    run_mode: Literal["inprocess", "http"] = "http" if run_mode_env == "http" else "inprocess"
    pooling_env = _as_str(get("VLLM_POOLING_TYPE", "last")).strip().upper()
    if pooling_env in {"CLS", "MEAN"}:
        embedding_mode = cast("Literal['LAST','CLS','MEAN']", pooling_env)
    else:
        embedding_mode = "LAST"
    task_env = _as_optional_str(get("VLLM_TASK", None))
    task_value: Literal["embed"] | None = (
        "embed" if task_env and task_env.strip().lower() == "embed" else None
    )
    max_batched_tokens = _parse_int_with_suffix(get("VLLM_MAX_BATCHED_TOKENS", "65536"), 65_536)
    normalize = _to_bool(_as_optional_str(get("VLLM_NORMALIZE", "1")), default=True)
    return VLLMSettings(
        base_url=_as_str(get("VLLM_URL", "http://127.0.0.1:8001/v1")),
        model=_as_str(get("VLLM_MODEL", "nomic-ai/nomic-embed-code")),
        batch_size=_coerce_int(get("VLLM_BATCH_SIZE", "64"), default=64),
        embedding_dim=_coerce_int(get("VLLM_EMBED_DIM", "3584"), default=3584),
        timeout_s=_coerce_float(get("VLLM_TIMEOUT_S", "120.0"), default=120.0),
        run_mode=run_mode,
        memory_utilization=_coerce_float(get("VLLM_MEMORY_UTILIZATION", "0.92"), default=0.92),
        max_num_batched_tokens=max_batched_tokens,
        normalize=normalize,
        embedding_mode=embedding_mode,
        max_concurrent_requests=_coerce_int(get("VLLM_MAX_CONCURRENT_REQUESTS", "4"), default=4),
        task=task_value,
    )


def _resolve_bm25_analyzer(raw: object) -> Literal["code", "standard"]:
    """Resolve BM25 analyzer type from raw configuration value.

    Parameters
    ----------
    raw : object
        Raw configuration value to parse. Can be any type convertible to string.

    Returns
    -------
    Literal["code", "standard"]
        "standard" if the normalized value equals "standard" (case-insensitive),
        otherwise "code" as the default analyzer type.
    """
    normalized = _as_str(raw).strip().lower()
    if normalized == "standard":
        return "standard"
    return "code"


def _bm25_settings(get: LookupFn, paths: PathsConfig) -> BM25Settings:
    """Build BM25Settings from lookup function with defaults.

    Parameters
    ----------
    get : LookupFn
        Lookup function that retrieves configuration values by name.
    paths : PathsConfig
        Paths configuration for resolving repository-relative paths and defaults.

    Returns
    -------
    BM25Settings
        BM25 configuration with all fields populated from environment variables
        and file data, using defaults when values are not specified.
    """
    default_json = paths.data_dir / "bm25_json"
    corpus_dir = _repo_path(paths, get("BM25_JSONL_DIR", default_json), default=default_json)
    default_index = paths.repo_root / "indexes" / "bm25"
    index_dir = _repo_path(paths, get("BM25_INDEX_DIR", default_index), default=default_index)
    threads = _coerce_int(get("BM25_THREADS", "8"), default=8)
    enabled = _to_bool(_as_optional_str(get("HYBRID_ENABLE_BM25", "true")), default=True)
    k1 = _coerce_float(get("BM25_K1", "0.9"), default=0.9)
    b = _coerce_float(get("BM25_B", "0.4"), default=0.4)
    rm3_enabled = _to_bool(_as_optional_str(get("BM25_RM3_ENABLED", "false")), default=False)
    rm3_fb_docs = _coerce_int(get("BM25_RM3_FB_DOCS", "10"), default=10)
    rm3_fb_terms = _coerce_int(get("BM25_RM3_FB_TERMS", "10"), default=10)
    rm3_orig_weight = _coerce_float(get("BM25_RM3_ORIG_WEIGHT", "0.5"), default=0.5)
    analyzer = _resolve_bm25_analyzer(get("BM25_ANALYZER", "code"))
    stopwords_raw = _as_optional_str(get("BM25_STOPWORDS", ""))
    stopwords = tuple(
        word.strip() for word in (stopwords_raw.split(",") if stopwords_raw else []) if word.strip()
    )
    return BM25Settings(
        corpus_json_dir=corpus_dir,
        index_dir=index_dir,
        threads=threads,
        enabled=enabled,
        k1=k1,
        b=b,
        rm3_enabled=rm3_enabled,
        rm3_fb_docs=rm3_fb_docs,
        rm3_fb_terms=rm3_fb_terms,
        rm3_original_query_weight=rm3_orig_weight,
        analyzer=analyzer,
        stopwords=stopwords,
    )


def _resolve_splade_analyzer(raw: object) -> Literal["wordpiece", "code"]:
    """Resolve SPLADE analyzer type from raw configuration value.

    Parameters
    ----------
    raw : object
        Raw configuration value to parse. Can be any type convertible to string.

    Returns
    -------
    Literal["wordpiece", "code"]
        "code" if the normalized value equals "code" (case-insensitive),
        otherwise "wordpiece" as the default analyzer type.
    """
    normalized = _as_str(raw).strip().lower()
    if normalized == "code":
        return "code"
    return "wordpiece"


def _splade_onnx_query_config(
    get: LookupFn,
    paths: PathsConfig,
    *,
    model_id: str,
    provider: str,
) -> SpladeOnnxQueryConfig | None:
    """Build SPLADE ONNX query encoder configuration from lookup function.

    Parameters
    ----------
    get : LookupFn
        Lookup function that retrieves configuration values by name.
    paths : PathsConfig
        Paths configuration for resolving repository-relative model paths.
    model_id : str
        Default model identifier used for tokenizer name if not specified.
    provider : str
        Default ONNX execution provider used if providers are not specified.

    Returns
    -------
    SpladeOnnxQueryConfig | None
        ONNX query encoder configuration if enabled, None if ONNX encoding
        is disabled or not configured.
    """
    use_onnx = _to_bool(
        _as_optional_str(get("SPLADE_USE_ONNX_QUERY_ENCODER", "false")), default=False
    )
    if not use_onnx:
        return None
    raw_providers = _as_optional_str(get("SPLADE_ONNX_QUERY_PROVIDERS", ""))
    providers = tuple(part.strip() for part in (raw_providers or "").split(",") if part.strip())
    if not providers:
        providers = (provider,)
    raw_format = _as_str(get("SPLADE_ONNX_QUERY_FORMAT", "string")).strip().lower()
    fmt: Literal["string", "map"] = "map" if raw_format == "map" else "string"
    model_path = _optional_repo_path(paths, get("SPLADE_ONNX_QUERY_MODEL", None))
    tokenizer_name = _as_optional_str(get("SPLADE_ONNX_QUERY_TOKENIZER", None)) or model_id
    output_name = _as_str(get("SPLADE_ONNX_QUERY_OUTPUT", "logits"))
    input_ids_name = _as_str(get("SPLADE_ONNX_QUERY_INPUT_IDS", "input_ids"))
    attention_mask_name = _as_str(get("SPLADE_ONNX_QUERY_ATTENTION_MASK", "attention_mask"))
    topn_default = _coerce_int(get("SPLADE_MAX_QUERY_TERMS", "64"), default=64)
    topn = _coerce_int(get("SPLADE_ONNX_QUERY_TOPN", str(topn_default)), default=topn_default)
    min_weight = _coerce_float(get("SPLADE_ONNX_QUERY_MIN_WEIGHT", "1e-6"), default=1e-6)
    normalize = _to_bool(
        _as_optional_str(get("SPLADE_ONNX_QUERY_NORMALIZE", "false")), default=False
    )
    return SpladeOnnxQueryConfig(
        enabled=True,
        model_path=model_path,
        tokenizer_name=tokenizer_name,
        output_name=output_name,
        input_ids_name=input_ids_name,
        attention_mask_name=attention_mask_name,
        providers=providers,
        topn=topn,
        min_weight=min_weight,
        normalize=normalize,
        format=fmt,
    )


@dataclass(frozen=True, slots=True)
class _SpladeDirs:
    """Container for SPLADE directory paths.

    Attributes
    ----------
    model_dir : Path
        Directory containing SPLADE model files.
    onnx_dir : Path
        Directory containing ONNX model files.
    vectors_dir : Path
        Directory containing SPLADE vector embeddings.
    index_dir : Path
        Directory containing SPLADE search indexes.
    """

    model_dir: Path
    onnx_dir: Path
    vectors_dir: Path
    index_dir: Path


@dataclass(frozen=True, slots=True)
class _SpladeNumeric:
    """Container for SPLADE numeric configuration values.

    Attributes
    ----------
    quantization : int
        Quantization level for model weights (typically 100 for int8).
    max_terms : int
        Maximum number of terms in SPLADE representations.
    max_clause_count : int
        Maximum number of clauses in boolean queries.
    batch_size : int
        Batch size for batch processing operations.
    threads : int
        Number of threads for parallel processing.
    max_query_terms : int
        Maximum number of terms to extract from queries.
    """

    quantization: int
    max_terms: int
    max_clause_count: int
    batch_size: int
    threads: int
    max_query_terms: int


def _resolve_splade_dirs(paths: PathsConfig, get: LookupFn) -> _SpladeDirs:
    """Resolve SPLADE directory paths from configuration with defaults.

    Parameters
    ----------
    paths : PathsConfig
        Paths configuration containing repository root and data directory.
    get : LookupFn
        Lookup function that retrieves configuration values by name.

    Returns
    -------
    _SpladeDirs
        Container with resolved paths for model, ONNX, vectors, and index
        directories. Paths are resolved relative to repository root if not absolute.
    """
    model_default = paths.repo_root / "models" / "splade-v3"
    model_dir = _repo_path(paths, get("SPLADE_MODEL_DIR", model_default), default=model_default)
    onnx_default = model_dir / "onnx"
    onnx_dir = _repo_path(paths, get("SPLADE_ONNX_DIR", onnx_default), default=onnx_default)
    vectors_default = paths.data_dir / "splade_vectors"
    vectors_dir = _repo_path(
        paths, get("SPLADE_VECTORS_DIR", vectors_default), default=vectors_default
    )
    index_default = paths.repo_root / "indexes" / "splade_v3_impact"
    index_dir = _repo_path(paths, get("SPLADE_INDEX_DIR", index_default), default=index_default)
    return _SpladeDirs(
        model_dir=model_dir,
        onnx_dir=onnx_dir,
        vectors_dir=vectors_dir,
        index_dir=index_dir,
    )


def _resolve_splade_numeric(get: LookupFn) -> _SpladeNumeric:
    """Resolve SPLADE numeric configuration values from lookup function.

    Parameters
    ----------
    get : LookupFn
        Lookup function that retrieves configuration values by name.

    Returns
    -------
    _SpladeNumeric
        Container with numeric configuration values including quantization,
        term limits, clause limits, batch size, thread count, and query term limits.
    """
    return _SpladeNumeric(
        quantization=_coerce_int(get("SPLADE_QUANTIZATION", "100"), default=100),
        max_terms=_coerce_int(get("SPLADE_MAX_TERMS", "3000"), default=3000),
        max_clause_count=_coerce_int(get("SPLADE_MAX_CLAUSE", "4096"), default=4096),
        batch_size=_coerce_int(get("SPLADE_BATCH_SIZE", "32"), default=32),
        threads=_coerce_int(get("SPLADE_THREADS", "8"), default=8),
        max_query_terms=_coerce_int(get("SPLADE_MAX_QUERY_TERMS", "64"), default=64),
    )


def _splade_settings(get: LookupFn, paths: PathsConfig) -> SpladeSettings:
    """Build SpladeSettings from lookup function with defaults.

    Parameters
    ----------
    get : LookupFn
        Lookup function that retrieves configuration values by name.
    paths : PathsConfig
        Paths configuration for resolving repository-relative paths.

    Returns
    -------
    SpladeSettings
        Complete SPLADE configuration including model ID, directory paths,
        execution provider, numeric settings, analyzer type, pruning thresholds,
        and optional ONNX query encoder configuration.
    """
    model_id = _as_str(get("SPLADE_MODEL_ID", "naver/splade-v3"))
    dirs = _resolve_splade_dirs(paths, get)
    provider = _as_str(get("SPLADE_PROVIDER", "CPUExecutionProvider"))
    numeric = _resolve_splade_numeric(get)
    enabled = _to_bool(_as_optional_str(get("HYBRID_ENABLE_SPLADE", "true")), default=True)
    prune_below = _coerce_float(get("SPLADE_PRUNE_BELOW", "0.0"), default=0.0)
    analyzer = _resolve_splade_analyzer(get("SPLADE_ANALYZER", "wordpiece"))
    static_prune_pct = _coerce_float(get("SPLADE_STATIC_PRUNE_PCT", "0.0"), default=0.0)
    onnx_query = _splade_onnx_query_config(get, paths, model_id=model_id, provider=provider)
    return SpladeSettings(
        model_id=model_id,
        model_dir=dirs.model_dir,
        onnx_dir=dirs.onnx_dir,
        onnx_file=_as_str(get("SPLADE_ONNX_FILE", "model_qint8.onnx")),
        vectors_dir=dirs.vectors_dir,
        index_dir=dirs.index_dir,
        provider=provider,
        quantization=numeric.quantization,
        max_terms=numeric.max_terms,
        max_clause_count=numeric.max_clause_count,
        batch_size=numeric.batch_size,
        threads=numeric.threads,
        enabled=enabled,
        max_query_terms=numeric.max_query_terms,
        prune_below=prune_below,
        analyzer=analyzer,
        static_prune_pct=static_prune_pct,
        onnx_query=onnx_query,
    )


def _xtr_settings(get: LookupFn) -> XTRSettings:
    """Build XTRSettings from lookup function with defaults.

    Parameters
    ----------
    get : LookupFn
        Lookup function retrieving configuration values by name.

    Returns
    -------
    XTRSettings
        Token-level XTR configuration including model id, device, limits,
        dtype, and feature toggles.
    """
    model_id = _as_str(get("XTR_MODEL_ID", "nomic-ai/CodeRankEmbed"))
    device = _as_str(get("XTR_DEVICE", "cuda"))
    max_query_tokens = _coerce_int(get("XTR_MAX_QUERY_TOKENS", "256"), default=256)
    candidate_k = _coerce_int(get("XTR_CANDIDATE_K", "200"), default=200)
    dim = _coerce_int(get("XTR_DIM", "768"), default=768)
    dtype_env = _as_str(get("XTR_DTYPE", "float16")).strip().lower()
    dtype: Literal["float16", "float32"] = "float32" if dtype_env == "float32" else "float16"
    enable = _to_bool(_as_optional_str(get("XTR_ENABLE", "0")), default=False)
    mode_env = _as_str(get("XTR_MODE", "narrow")).strip().lower()
    mode: Literal["narrow", "wide"] = "wide" if mode_env == "wide" else "narrow"
    return XTRSettings(
        model_id=model_id,
        device=device,
        max_query_tokens=max_query_tokens,
        candidate_k=candidate_k,
        dim=dim,
        dtype=dtype,
        enable=enable,
        mode=mode,
    )


def _rrf_weights(get: LookupFn) -> dict[str, float]:
    """Return configured RRF weights.

    Parameters
    ----------
    get : LookupFn
        Lookup function that retrieves configuration values by name.

    Returns
    -------
    dict[str, float]
        Dictionary mapping channel names to RRF weight values.
    """
    return _parse_float_mapping(get("RRF_WEIGHTS_JSON", ""), default=_DEFAULT_RRF_WEIGHTS)


def _hybrid_prefetch_config(get: LookupFn) -> dict[str, int]:
    """Return hybrid prefetch limits.

    Parameters
    ----------
    get : LookupFn
        Lookup function that retrieves configuration values by name.

    Returns
    -------
    dict[str, int]
        Dictionary mapping channel names to prefetch limit values.
    """
    return _parse_int_mapping(get("HYBRID_PREFETCH_JSON", ""), default=_DEFAULT_PREFETCH)


def _hybrid_weight_overrides(get: LookupFn) -> dict[str, float]:
    """Return hybrid weight overrides.

    Parameters
    ----------
    get : LookupFn
        Lookup function that retrieves configuration values by name.

    Returns
    -------
    dict[str, float]
        Dictionary mapping channel names to weight override values.
    """
    return _parse_float_mapping(get("HYBRID_WEIGHTS_OVERRIDE_JSON", ""), default={})


def _prf_settings(get: LookupFn) -> PRFSettings:
    """Return pseudo relevance feedback settings.

    Parameters
    ----------
    get : LookupFn
        Lookup function that retrieves configuration values by name.

    Returns
    -------
    PRFSettings
        Pseudo relevance feedback configuration settings.
    """
    return PRFSettings(
        enable_auto=_to_bool(_as_optional_str(get("BM25_PRF_ENABLE_AUTO", None)), default=True),
        fb_docs=_coerce_int(get("BM25_PRF_FB_DOCS", "10"), default=10),
        fb_terms=_coerce_int(get("BM25_PRF_FB_TERMS", "10"), default=10),
        orig_weight=_coerce_float(get("BM25_PRF_ORIG_WEIGHT", "0.5"), default=0.5),
        short_query_max_terms=_coerce_int(get("BM25_PRF_SHORT_QUERY_MAX_TERMS", "3"), default=3),
        symbol_like_regex=_as_optional_str(get("BM25_PRF_SYMBOL_REGEX", None)),
        head_terms_csv=_as_optional_str(get("BM25_PRF_HEAD_TERMS_CSV", None)),
    )


def _index_settings(get: LookupFn) -> IndexSettings:
    """Return IndexSettings populated from lookup.

    Parameters
    ----------
    get : LookupFn
        Lookup function that retrieves configuration values by name.

    Returns
    -------
    IndexSettings
        Index configuration settings including vector dimension, recency settings,
        and other index parameters.
    """
    recency_enabled = _to_bool(_as_optional_str(get("INDEX_RECENCY_ENABLED", None)), default=False)
    recency_half_life = _coerce_float(get("INDEX_RECENCY_HALF_LIFE_DAYS", "30.0"), default=30.0)
    recency_max_boost = _coerce_float(get("INDEX_RECENCY_MAX_BOOST", "0.15"), default=0.15)
    recency_table = _as_str(get("INDEX_RECENCY_TABLE", "chunks"))
    return IndexSettings(
        vec_dim=_coerce_int(get("VEC_DIM", "3584"), default=3584),
        chunk_budget=_coerce_int(get("CHUNK_BUDGET", "2200"), default=2200),
        faiss_nlist=_coerce_int(get("FAISS_NLIST", "8192"), default=8192),
        faiss_nprobe=_coerce_int(get("FAISS_NPROBE", "128"), default=128),
        bm25_k1=_coerce_float(get("BM25_K1", "0.9"), default=0.9),
        bm25_b=_coerce_float(get("BM25_B", "0.4"), default=0.4),
        rrf_k=_coerce_int(get("RRF_K", "60"), default=60),
        enable_bm25_channel=_to_bool(
            _as_optional_str(get("HYBRID_ENABLE_BM25", None)), default=True
        ),
        enable_splade_channel=_to_bool(
            _as_optional_str(get("HYBRID_ENABLE_SPLADE", None)),
            default=True,
        ),
        hybrid_top_k_per_channel=_coerce_int(
            get("HYBRID_TOP_K_PER_CHANNEL", "50"),
            default=50,
        ),
        faiss_preload=_to_bool(_as_optional_str(get("FAISS_PRELOAD", None)), default=False),
        duckdb_materialize=_to_bool(
            _as_optional_str(get("DUCKDB_MATERIALIZE", None)), default=False
        ),
        preview_max_chars=_coerce_int(get("PREVIEW_MAX_CHARS", "240"), default=240),
        compaction_threshold=_coerce_float(
            get("FAISS_COMPACTION_THRESHOLD", "0.05"),
            default=0.05,
        ),
        rrf_weights=_rrf_weights(get),
        hybrid_prefetch=_hybrid_prefetch_config(get),
        hybrid_use_rrf=_to_bool(_as_optional_str(get("HYBRID_USE_RRF", None)), default=True),
        hybrid_weights_override=_hybrid_weight_overrides(get),
        prf=_prf_settings(get),
        recency_enabled=recency_enabled,
        recency_half_life_days=recency_half_life,
        recency_max_boost=recency_max_boost,
        recency_table=recency_table,
    )


def _app_config_from_lookup(get: LookupFn) -> AppConfig:
    """Build complete AppConfig from lookup function.

    Parameters
    ----------
    get : LookupFn
        Lookup function that retrieves configuration values by name.

    Returns
    -------
    AppConfig
        Complete application configuration with all subsystem settings
        (paths, DuckDB, FAISS, SPLADE, search, logging) resolved from
        environment variables and configuration files.
    """
    paths = _paths_config(get)
    vllm = _vllm_settings(get)
    embeddings = _embeddings_settings(get)
    return AppConfig(
        version=str(get("CONFIG_API_VERSION", CONFIG_API_VERSION)),
        paths=paths,
        duckdb=_duckdb_settings(get, paths.data_dir),
        faiss=_faiss_settings(get, paths.data_dir),
        bm25=_bm25_settings(get, paths),
        splade=_splade_settings(get, paths),
        xtr=_xtr_settings(get),
        index=_index_settings(get),
        embeddings=embeddings,
        vllm=vllm,
        search=_search_settings(get),
        logging=_logging_settings(get),
        eval=_eval_settings(paths, get),
    )


def load_app_config(
    *, file: str | Path | None = None, env: Mapping[str, str] | None = None
) -> AppConfig:
    """Load :class:`AppConfig` by merging defaults, file overrides, and env vars.

    Parameters
    ----------
    file : str | Path | None, optional
        Optional path to a JSON/YAML config file.
    env : Mapping[str, str] | None, optional
        Optional environment mapping; defaults to :data:`os.environ`.

    Returns
    -------
    AppConfig
        Fully validated application configuration.

    Raises
    ------
    ImportError
        If YAML parsing is requested but PyYAML is unavailable.
    ValueError
        If resulting configuration fails validation.
    """
    environ = env or os.environ
    file_path = Path(str(file)) if file else None
    try:
        file_data: Mapping[str, object] = _load_file(file_path) if file_path else {}
    except ImportError as exc:
        message = "Unable to parse configuration file"
        raise ImportError(message) from exc
    lookup = _build_lookup(environ, file_data)

    cfg = _app_config_from_lookup(lookup)
    try:
        validate_config(cfg)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    return cfg
