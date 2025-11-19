"""Tests for the config loader."""

from __future__ import annotations

import json
from pathlib import Path

from codeintel_rev.config.loader import load_app_config

from tests._helpers import assertions


def test_env_values_override_defaults(tmp_path: Path) -> None:
    """Environment-provided values should take precedence over defaults."""
    repo_root = tmp_path / "env_repo"
    env = {
        "BASE_DIR": str(repo_root),
        "DUCKDB_THREADS": "8",
        "DUCKDB_OBJECT_CACHE": "0",
        "DUCKDB_TEMP_DIR": str(tmp_path / "tmp"),
        "DUCKDB_POOL_SIZE": "16",
        "FAISS_INDEX_PATH": str(tmp_path / "env_index.faiss"),
        "FAISS_DEFAULT_K": "42",
        "FAISS_DEFAULT_NPROBE": "128",
        "FAISS_REFINE_K_FACTOR": "2.5",
        "SEARCH_BM25_WEIGHT": "0.1",
        "SEARCH_SPLADE_WEIGHT": "0.4",
        "SEARCH_FAISS_WEIGHT": "0.5",
        "SEARCH_MAX_RESULTS": "25",
        "LOG_LEVEL": "DEBUG",
        "LOG_JSON": "1",
    }
    cfg = load_app_config(env=env)
    assertions.expect_equal(cfg.paths.repo_root, repo_root.resolve(strict=False))
    assertions.expect_equal(cfg.duckdb.threads, 8)
    assertions.expect_false(cfg.duckdb.object_cache)
    assertions.expect_equal(
        cfg.duckdb.temp_directory, Path(env["DUCKDB_TEMP_DIR"]).resolve(strict=False)
    )
    assertions.expect_equal(cfg.duckdb.pool_size, 16)
    assertions.expect_equal(
        cfg.faiss.index_path, Path(env["FAISS_INDEX_PATH"]).resolve(strict=False)
    )
    assertions.expect_equal(cfg.faiss.default_k, 42)
    assertions.expect_equal(cfg.faiss.default_nprobe, 128)
    assertions.expect_equal(cfg.faiss.refine_k_factor, 2.5)
    assertions.expect_equal(cfg.search.max_results, 25)
    assertions.expect_equal(cfg.logging.level, "DEBUG")
    assertions.expect_true(cfg.logging.json)


def test_loader_reads_file_and_env_precedence(tmp_path: Path) -> None:
    """File-provided settings should load, with env overrides taking precedence."""
    cfg_file = tmp_path / "config.json"
    base_dir = str(tmp_path / "file_repo")
    file_values = {
        "BASE_DIR": base_dir,
        "FAISS_DEFAULT_K": 60,
        "SEARCH_MAX_RESULTS": 9,
    }
    cfg_file.write_text(json.dumps(file_values), encoding="utf-8")
    cfg = load_app_config(file=cfg_file)
    assertions.expect_equal(cfg.paths.repo_root, Path(base_dir).resolve(strict=False))
    assertions.expect_equal(cfg.faiss.default_k, 60)
    assertions.expect_equal(cfg.search.max_results, 9)

    cfg = load_app_config(file=cfg_file, env={"FAISS_DEFAULT_K": "99"})
    assertions.expect_equal(cfg.faiss.default_k, 99)
