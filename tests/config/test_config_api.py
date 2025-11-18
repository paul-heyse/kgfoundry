"""Tests for the immutable config API."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from codeintel_rev.config.api import (
    AppConfig,
    DuckDBSettings,
    FAISSSettings,
    LoggingSettings,
    PathsConfig,
    SearchSettings,
    validate_config,
)


def _make_config(tmp_path: Path) -> AppConfig:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    paths = PathsConfig(
        repo_root=repo_root,
        data_dir=repo_root / "data",
        cache_dir=repo_root / "cache",
        logs_dir=repo_root / "logs",
    )
    duckdb = DuckDBSettings(database=repo_root / "catalog.duckdb")
    faiss = FAISSSettings(index_path=repo_root / "index.faiss")
    search = SearchSettings()
    logging_cfg = LoggingSettings()
    return AppConfig(
        version="1.0",
        paths=paths,
        duckdb=duckdb,
        faiss=faiss,
        search=search,
        logging=logging_cfg,
    )


def test_app_config_is_immutable(tmp_path: Path) -> None:
    """Assignments should fail on frozen dataclasses."""
    cfg = _make_config(tmp_path)
    with pytest.raises(FrozenInstanceError):
        cfg.paths.repo_root = tmp_path  # type: ignore[misc]


def test_validate_config_rejects_invalid_values(tmp_path: Path) -> None:
    """validate_config enforces positive numeric values."""
    cfg = _make_config(tmp_path)
    bad_k = replace(cfg, faiss=replace(cfg.faiss, default_k=0))
    with pytest.raises(ValueError, match="faiss\\.default_k"):
        validate_config(bad_k)
    bad_nprobe = replace(cfg, faiss=replace(cfg.faiss, default_nprobe=0))
    with pytest.raises(ValueError, match="faiss\\.default_nprobe"):
        validate_config(bad_nprobe)
    bad_refine = replace(cfg, faiss=replace(cfg.faiss, refine_k_factor=0.0))
    with pytest.raises(ValueError, match="faiss\\.refine_k_factor"):
        validate_config(bad_refine)
    bad_search = replace(cfg, search=replace(cfg.search, max_results=0))
    with pytest.raises(ValueError, match="search\\.max_results"):
        validate_config(bad_search)
