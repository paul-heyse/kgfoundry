"""Load application configuration from environment variables and optional files."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, MutableMapping
from pathlib import Path
from typing import Literal, cast

from codeintel_rev.config.api import (
    CONFIG_API_VERSION,
    AppConfig,
    DuckDBSettings,
    FAISSSettings,
    LoggingSettings,
    PathsConfig,
    SearchSettings,
    SpladeOnnxQueryConfig,
    SpladeSettings,
    validate_config,
)
from codeintel_rev.runtime.imports import gate_import

LookupFn = Callable[[str, object], object]


def _to_bool(value: str | None, *, default: bool = False) -> bool:
    normalized = (value or "").strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _coerce_int(value: object, *, default: int) -> int:
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


def _coerce_float(value: object, *, default: float) -> float:
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


def _load_file(path: Path) -> Mapping[str, object]:
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
    return Path(value).expanduser().resolve(strict=False)


def _optional_path(value: object) -> Path | None:
    if isinstance(value, (str, Path)) and value:
        return _as_path(value)
    return None


def _resolve_repo_path(paths: PathsConfig, value: Path) -> Path:
    candidate = value
    if not candidate.is_absolute():
        candidate = paths.repo_root / candidate
    return candidate.expanduser().resolve(strict=False)


def _repo_path(paths: PathsConfig, raw_value: object, *, default: Path) -> Path:
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
    return str(value)


def _as_optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _build_lookup(env: Mapping[str, str], file_data: Mapping[str, object]) -> LookupFn:
    def _get(name: str, default: object) -> object:
        if name in env:
            return env[name]
        if name in file_data:
            return file_data[name]
        return default

    return _get


def _paths_config(get: LookupFn) -> PathsConfig:
    repo_root = _as_path(_as_str(get("BASE_DIR", Path.cwd())))
    data_dir = _as_path(_as_str(get("DATA_DIR", repo_root / "data")))
    cache_dir = _as_path(_as_str(get("CACHE_DIR", repo_root / ".cache")))
    logs_dir = _as_path(_as_str(get("LOGS_DIR", repo_root / "logs")))
    return PathsConfig(
        repo_root=repo_root, data_dir=data_dir, cache_dir=cache_dir, logs_dir=logs_dir
    )


def _duckdb_settings(get: LookupFn, data_dir: Path) -> DuckDBSettings:
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
    level = _as_str(get("LOG_LEVEL", "INFO"))
    as_json = _to_bool(_as_optional_str(get("LOG_JSON", "false")), default=False)
    return LoggingSettings(level=level, json=as_json)


def _resolve_splade_analyzer(raw: object) -> Literal["wordpiece", "code"]:
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
    use_onnx = _to_bool(_as_optional_str(get("SPLADE_USE_ONNX_QUERY_ENCODER", "false")), default=False)
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
    normalize = _to_bool(_as_optional_str(get("SPLADE_ONNX_QUERY_NORMALIZE", "false")), default=False)
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


def _splade_settings(get: LookupFn, paths: PathsConfig) -> SpladeSettings:
    model_id = _as_str(get("SPLADE_MODEL_ID", "naver/splade-v3"))
    default_model_dir = paths.repo_root / "models" / "splade-v3"
    model_dir = _repo_path(paths, get("SPLADE_MODEL_DIR", default_model_dir), default=default_model_dir)
    default_onnx_dir = model_dir / "onnx"
    onnx_dir = _repo_path(paths, get("SPLADE_ONNX_DIR", default_onnx_dir), default=default_onnx_dir)
    onnx_file = _as_str(get("SPLADE_ONNX_FILE", "model_qint8.onnx"))
    default_vectors_dir = paths.data_dir / "splade_vectors"
    vectors_dir = _repo_path(
        paths,
        get("SPLADE_VECTORS_DIR", default_vectors_dir),
        default=default_vectors_dir,
    )
    default_index_dir = paths.repo_root / "indexes" / "splade_v3_impact"
    index_dir = _repo_path(
        paths,
        get("SPLADE_INDEX_DIR", default_index_dir),
        default=default_index_dir,
    )
    provider = _as_str(get("SPLADE_PROVIDER", "CPUExecutionProvider"))
    quantization = _coerce_int(get("SPLADE_QUANTIZATION", "100"), default=100)
    max_terms = _coerce_int(get("SPLADE_MAX_TERMS", "3000"), default=3000)
    max_clause = _coerce_int(get("SPLADE_MAX_CLAUSE", "4096"), default=4096)
    batch_size = _coerce_int(get("SPLADE_BATCH_SIZE", "32"), default=32)
    threads = _coerce_int(get("SPLADE_THREADS", "8"), default=8)
    enabled = _to_bool(_as_optional_str(get("HYBRID_ENABLE_SPLADE", "true")), default=True)
    max_query_terms = _coerce_int(get("SPLADE_MAX_QUERY_TERMS", "64"), default=64)
    prune_below = _coerce_float(get("SPLADE_PRUNE_BELOW", "0.0"), default=0.0)
    analyzer = _resolve_splade_analyzer(get("SPLADE_ANALYZER", "wordpiece"))
    static_prune_pct = _coerce_float(get("SPLADE_STATIC_PRUNE_PCT", "0.0"), default=0.0)
    onnx_query = _splade_onnx_query_config(get, paths, model_id=model_id, provider=provider)
    return SpladeSettings(
        model_id=model_id,
        model_dir=model_dir,
        onnx_dir=onnx_dir,
        onnx_file=onnx_file,
        vectors_dir=vectors_dir,
        index_dir=index_dir,
        provider=provider,
        quantization=quantization,
        max_terms=max_terms,
        max_clause_count=max_clause,
        batch_size=batch_size,
        threads=threads,
        enabled=enabled,
        max_query_terms=max_query_terms,
        prune_below=prune_below,
        analyzer=analyzer,
        static_prune_pct=static_prune_pct,
        onnx_query=onnx_query,
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

    paths = _paths_config(lookup)
    duckdb = _duckdb_settings(lookup, paths.data_dir)
    faiss = _faiss_settings(lookup, paths.data_dir)
    search = _search_settings(lookup)
    logging_cfg = _logging_settings(lookup)
    splade = _splade_settings(lookup, paths)
    extras: MutableMapping[str, object] = {}

    cfg = AppConfig(
        version=str(lookup("CONFIG_API_VERSION", CONFIG_API_VERSION)),
        paths=paths,
        duckdb=duckdb,
        faiss=faiss,
        splade=splade,
        search=search,
        logging=logging_cfg,
        extras=extras,
    )
    try:
        validate_config(cfg)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    return cfg
