"""Tests for the pure path resolver."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from codeintel_rev.config.paths import resolve_application_paths

from tests._helpers.assertions import expect_equal, expect_true
from tests._helpers.settings import build_app_config_from_paths, build_settings_for_repo


def test_resolve_application_paths_from_settings(tmp_path: Path) -> None:
    """Resolver canonicalizes repo-relative settings without touching the FS."""
    repo_root = tmp_path / "repo"
    settings = build_settings_for_repo(repo_root)

    paths = resolve_application_paths(settings)

    expect_equal(paths.repo_root, repo_root.resolve(), reason="repo root normalized")
    expect_equal(paths.vectors_dir.parent, paths.data_dir, reason="vectors parent matches data_dir")
    expect_true(paths.faiss_index.is_absolute(), reason="faiss path absolute")
    expect_equal(
        paths.config_dir, repo_root.resolve() / "config", reason="config dir relative to repo"
    )
    expect_equal(paths.logs_dir, repo_root.resolve() / "logs", reason="logs dir relative to repo")


def test_resolve_application_paths_accepts_mapping(tmp_path: Path) -> None:
    """Resolver supports dict-style overrides for non-Settings callers."""
    repo_root = tmp_path / "workspace"
    settings = {
        "BASE_DIR": str(repo_root),
        "DATA_DIR": "datasets",
        "CONFIG_FILE": "conf/runtime.yml",
        "CODERANK_FAISS_INDEX": repo_root / "indexes" / "coderank.faiss",
    }

    paths = resolve_application_paths(settings)

    expect_equal(paths.repo_root, repo_root.resolve(), reason="repo root normalized via BASE_DIR")
    expect_equal(
        paths.data_dir, (repo_root / "datasets").resolve(), reason="DATA_DIR override honored"
    )
    expect_equal(
        paths.config_file,
        (repo_root / "conf" / "runtime.yml").resolve(),
        reason="CONFIG_FILE override honored",
    )
    expect_equal(
        paths.coderank_faiss_index,
        (repo_root / "indexes" / "coderank.faiss").resolve(),
        reason="CODERANK_FAISS_INDEX override honored",
    )


def test_resolved_paths_hashable(tmp_path: Path) -> None:
    """ResolvedPaths instances are hashable for use as cache keys."""
    repo_root = tmp_path / "hashable"
    settings = build_settings_for_repo(repo_root)
    paths = resolve_application_paths(settings)
    expect_true(isinstance(hash(paths), int), reason="hashable dataclass")

    another_paths = replace(paths)
    expect_equal(paths, another_paths, reason="dataclass equality uses field values")
    expect_equal(hash(paths), hash(another_paths), reason="hash remains stable for clones")


def test_resolve_application_paths_from_app_config(tmp_path: Path) -> None:
    """Resolver builds canonical paths from AppConfig inputs."""
    repo_root = tmp_path / "appcfg"
    repo_root.mkdir(parents=True, exist_ok=True)
    settings = build_settings_for_repo(repo_root)
    baseline = resolve_application_paths(settings)
    app_config = build_app_config_from_paths(baseline)

    resolved = resolve_application_paths(app_config)

    expect_equal(resolved.repo_root, baseline.repo_root, reason="repo root preserved")
    expect_equal(resolved.faiss_index, app_config.faiss.index_path, reason="faiss path from config")
    expect_equal(
        resolved.duckdb_path,
        app_config.duckdb.database,
        reason="duckdb path sourced from AppConfig",
    )
    expect_equal(resolved.logs_dir, (repo_root / "logs").resolve(), reason="logs dir canonicalized")
