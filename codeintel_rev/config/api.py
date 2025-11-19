"""Immutable, versioned configuration data models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

CONFIG_API_VERSION: Final[str] = "1.0"


@dataclass(frozen=True, slots=True)
class PathsConfig:
    """Filesystem paths used by the application."""

    repo_root: Path
    data_dir: Path
    cache_dir: Path
    logs_dir: Path


@dataclass(frozen=True, slots=True)
class DuckDBSettings:
    """Settings for the DuckDB subsystem."""

    database: Path
    threads: int | None = None
    object_cache: bool = True
    temp_directory: Path | None = None
    pool_size: int = 4


@dataclass(frozen=True, slots=True)
class FAISSSettings:
    """Settings for the FAISS subsystem."""

    index_path: Path
    default_k: int = 50
    default_nprobe: int = 64
    refine_k_factor: float = 1.0


@dataclass(frozen=True, slots=True)
class SearchSettings:
    """Settings for hybrid search weighting and Stage-0 tuning."""

    bm25_weight: float = 0.2
    splade_weight: float = 0.3
    faiss_weight: float = 0.5
    per_channel_k: int = 100
    fusion_k: int = 50
    rrf_base: int = 60
    max_results: int = 50


@dataclass(frozen=True, slots=True)
class LoggingSettings:
    """Settings for log output."""

    level: str = "INFO"
    json: bool = False


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Top-level immutable configuration."""

    version: str
    paths: PathsConfig
    duckdb: DuckDBSettings
    faiss: FAISSSettings
    search: SearchSettings = field(default_factory=SearchSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
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

    Raises
    ------
    ValueError
        If any invariants fail validation.
    """
    if not is_compatible_version(cfg.version):
        message = f"Incompatible config version {cfg.version!r}; expected {CONFIG_API_VERSION}"
        raise ValueError(message)
    if cfg.faiss.default_k <= 0:
        message = "faiss.default_k must be positive"
        raise ValueError(message)
    if cfg.faiss.default_nprobe <= 0:
        message = "faiss.default_nprobe must be positive"
        raise ValueError(message)
    if cfg.faiss.refine_k_factor <= 0:
        message = "faiss.refine_k_factor must be positive"
        raise ValueError(message)
    if cfg.search.max_results <= 0:
        message = "search.max_results must be positive"
        raise ValueError(message)
    if cfg.search.per_channel_k <= 0:
        message = "search.per_channel_k must be positive"
        raise ValueError(message)
    if cfg.search.fusion_k <= 0:
        message = "search.fusion_k must be positive"
        raise ValueError(message)
    if cfg.search.rrf_base <= 0:
        message = "search.rrf_base must be positive"
        raise ValueError(message)
