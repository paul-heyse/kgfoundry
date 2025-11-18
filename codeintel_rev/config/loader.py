"""Load application configuration from environment variables and optional files."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, MutableMapping
from pathlib import Path
from typing import cast

from codeintel_rev.config.api import (
    CONFIG_API_VERSION,
    AppConfig,
    DuckDBSettings,
    FAISSSettings,
    LoggingSettings,
    PathsConfig,
    SearchSettings,
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
    return PathsConfig(repo_root=repo_root, data_dir=data_dir, cache_dir=cache_dir, logs_dir=logs_dir)


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
    max_results = _coerce_int(get("SEARCH_MAX_RESULTS", "50"), default=50)
    return SearchSettings(
        bm25_weight=bm25_weight,
        splade_weight=splade_weight,
        faiss_weight=faiss_weight,
        max_results=max_results,
    )


def _logging_settings(get: LookupFn) -> LoggingSettings:
    level = _as_str(get("LOG_LEVEL", "INFO"))
    as_json = _to_bool(_as_optional_str(get("LOG_JSON", "false")), default=False)
    return LoggingSettings(level=level, json=as_json)


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
    extras: MutableMapping[str, object] = {}

    cfg = AppConfig(
        version=str(lookup("CONFIG_API_VERSION", CONFIG_API_VERSION)),
        paths=paths,
        duckdb=duckdb,
        faiss=faiss,
        search=search,
        logging=logging_cfg,
        extras=extras,
    )
    try:
        validate_config(cfg)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    return cfg
