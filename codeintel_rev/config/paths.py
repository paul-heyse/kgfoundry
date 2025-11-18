"""Pure path resolution utilities for CodeIntel applications."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from codeintel_rev.config.settings import PathsConfig, Settings

__all__ = ["ResolvedPaths", "resolve_application_paths"]

type PathInput = str | os.PathLike[str] | Path


@dataclass(frozen=True, slots=True)
class ResolvedPaths:
    """Immutable collection of canonical filesystem locations."""

    repo_root: Path
    config_dir: Path
    config_file: Path
    data_dir: Path
    vectors_dir: Path
    faiss_index: Path
    faiss_idmap_path: Path
    lucene_dir: Path
    splade_dir: Path
    duckdb_path: Path
    scip_index: Path
    coderank_vectors_dir: Path
    coderank_faiss_index: Path
    warp_index_dir: Path
    xtr_dir: Path
    logs_dir: Path
    cache_dir: Path
    tmp_dir: Path
    plugins_dir: Path


def _to_path(value: PathInput) -> Path:
    if isinstance(value, Path):
        return value
    return Path(value)


def _norm(path: Path) -> Path:
    expanded = path.expanduser()
    try:
        resolved = expanded.resolve(strict=False)
    except (OSError, RuntimeError):
        resolved = expanded
    if sys.platform.startswith("win"):
        return Path(os.path.normcase(str(resolved)))
    return resolved


def _resolve_relative(base: Path, candidate: PathInput) -> Path:
    raw = _to_path(candidate)
    if raw.is_absolute():
        return _norm(raw)
    return _norm(base / raw)


def _default_repo_root() -> Path:
    return _norm(Path(__file__).resolve().parents[2])


def _build_from_mapping(settings: Mapping[str, Any]) -> ResolvedPaths:
    repo_value = (
        settings.get("BASE_DIR") or settings.get("repo_root") or settings.get("paths_repo_root")
    )
    repo_root = (
        _norm(_to_path(cast("PathInput", repo_value)))
        if repo_value is not None
        else _default_repo_root()
    )

    def _setting(key: str, default: Path) -> Path:
        raw = settings.get(key)
        if raw is None:
            raw = settings.get(key.lower())
        return (
            _resolve_relative(repo_root, cast("PathInput", raw))
            if raw is not None
            else _norm(default)
        )

    config_dir = _setting("CONFIG_DIR", repo_root / "config")
    config_file_default = config_dir / "config.yaml"
    return ResolvedPaths(
        repo_root=repo_root,
        config_dir=config_dir,
        config_file=_setting("CONFIG_FILE", config_file_default),
        data_dir=_setting("DATA_DIR", repo_root / "data"),
        vectors_dir=_setting("VECTORS_DIR", repo_root / "data" / "vectors"),
        faiss_index=_setting(
            "FAISS_INDEX",
            repo_root / "data" / "faiss" / "code.ivfpq.faiss",
        ),
        faiss_idmap_path=_setting(
            "FAISS_IDMAP_PATH",
            repo_root / "data" / "faiss" / "faiss_idmap.parquet",
        ),
        lucene_dir=_setting("LUCENE_DIR", repo_root / "data" / "lucene"),
        splade_dir=_setting("SPLADE_DIR", repo_root / "data" / "splade"),
        duckdb_path=_setting("DUCKDB_PATH", repo_root / "data" / "catalog.duckdb"),
        scip_index=_setting("SCIP_INDEX", repo_root / "index.scip"),
        coderank_vectors_dir=_setting(
            "CODERANK_VECTORS_DIR",
            repo_root / "data" / "coderank_vectors",
        ),
        coderank_faiss_index=_setting(
            "CODERANK_FAISS_INDEX",
            repo_root / "data" / "faiss" / "coderank.ivfpq.faiss",
        ),
        warp_index_dir=_setting("WARP_INDEX_DIR", repo_root / "indexes" / "warp_xtr"),
        xtr_dir=_setting("XTR_DIR", repo_root / "data" / "xtr"),
        logs_dir=_setting("LOGS_DIR", repo_root / "logs"),
        cache_dir=_setting("CACHE_DIR", repo_root / ".cache"),
        tmp_dir=_setting("TMP_DIR", repo_root / ".tmp"),
        plugins_dir=_setting("PLUGINS_DIR", repo_root / "plugins"),
    )


def _build_from_settings(settings: Settings) -> ResolvedPaths:
    cfg: PathsConfig = settings.paths
    repo_root = _norm(_to_path(cfg.repo_root))

    def _resolve(value: str) -> Path:
        return _resolve_relative(repo_root, value)

    config_dir = _norm(repo_root / "config")
    config_file_default = _norm(config_dir / "config.yaml")
    return ResolvedPaths(
        repo_root=repo_root,
        config_dir=config_dir,
        config_file=config_file_default,
        data_dir=_resolve(cfg.data_dir),
        vectors_dir=_resolve(cfg.vectors_dir),
        faiss_index=_resolve(cfg.faiss_index),
        faiss_idmap_path=_resolve(cfg.faiss_idmap_path),
        lucene_dir=_resolve(cfg.lucene_dir),
        splade_dir=_resolve(cfg.splade_dir),
        duckdb_path=_resolve(cfg.duckdb_path),
        scip_index=_resolve(cfg.scip_index),
        coderank_vectors_dir=_resolve(cfg.coderank_vectors_dir),
        coderank_faiss_index=_resolve(cfg.coderank_faiss_index),
        warp_index_dir=_resolve(cfg.warp_index_dir),
        xtr_dir=_resolve(cfg.xtr_dir),
        logs_dir=_norm(repo_root / "logs"),
        cache_dir=_norm(repo_root / ".cache"),
        tmp_dir=_norm(repo_root / ".tmp"),
        plugins_dir=_norm(repo_root / "plugins"),
    )


def resolve_application_paths(settings: Settings | Mapping[str, Any]) -> ResolvedPaths:
    """Return canonical filesystem paths derived from ``settings``.

    Parameters
    ----------
    settings : Settings | Mapping[str, Any]
        Either a fully constructed :class:`Settings` instance or a mapping that
        mimics the environment layout (useful for tests and tooling).

    Returns
    -------
    ResolvedPaths
        Frozen dataclass capturing all filesystem inputs for the application.
        Paths are fully normalized (expanded, resolved, and case-normalized on
        Windows) so downstream consumers can rely on absolute locations.
    """
    if isinstance(settings, Mapping):
        return _build_from_mapping(settings)
    return _build_from_settings(settings)
