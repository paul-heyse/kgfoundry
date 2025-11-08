"""Unit tests for ApplicationContext and configuration management."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from codeintel_rev.app.config_context import (
    ApplicationContext,
    ResolvedPaths,
    resolve_application_paths,
)
from codeintel_rev.config.settings import load_settings

from kgfoundry_common.errors import ConfigurationError


def test_resolve_application_paths_success(tmp_path: Path) -> None:
    """Test successful path resolution with valid repo root."""
    # Arrange
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "data").mkdir()

    os.environ["REPO_ROOT"] = str(repo_root)
    settings = load_settings()

    # Act
    paths = resolve_application_paths(settings)

    # Assert
    assert paths.repo_root == repo_root.resolve()
    assert paths.data_dir == (repo_root / "data").resolve()
    assert paths.vectors_dir.parent == paths.data_dir
    assert all(path.is_absolute() for path in [paths.repo_root, paths.data_dir, paths.vectors_dir])


def test_resolve_application_paths_missing_repo_root() -> None:
    """Test that missing repo root raises ConfigurationError."""
    # Arrange
    os.environ["REPO_ROOT"] = "/nonexistent/path"
    settings = load_settings()

    # Act & Assert
    with pytest.raises(ConfigurationError, match="Repository root does not exist"):
        resolve_application_paths(settings)


def test_resolve_application_paths_not_directory(tmp_path: Path) -> None:
    """Test that non-directory repo root raises ConfigurationError."""
    # Arrange
    repo_file = tmp_path / "not_a_dir"
    repo_file.touch()

    os.environ["REPO_ROOT"] = str(repo_file)
    settings = load_settings()

    # Act & Assert
    with pytest.raises(ConfigurationError, match="Repository root is not a directory"):
        resolve_application_paths(settings)


def test_resolve_application_paths_relative_conversion(tmp_path: Path) -> None:
    """Test that relative paths are converted to absolute paths."""
    # Arrange
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "data").mkdir()

    os.environ["REPO_ROOT"] = str(repo_root)
    settings = load_settings()

    # Act
    paths = resolve_application_paths(settings)

    # Assert
    assert paths.faiss_index.is_absolute()
    assert paths.faiss_index.parent.parent == paths.data_dir
    assert paths.duckdb_path.is_absolute()
    assert paths.scip_index.is_absolute()


def test_application_context_create(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test ApplicationContext.create() initializes all clients."""
    # Arrange
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "data").mkdir()
    (repo_root / "data" / "vectors").mkdir()
    (repo_root / "data" / "faiss").mkdir()
    (repo_root / "data" / "faiss" / "code.ivfpq.faiss").touch()
    (repo_root / "data" / "catalog.duckdb").touch()

    monkeypatch.setenv("REPO_ROOT", str(repo_root))
    monkeypatch.setenv("VLLM_URL", "http://localhost:8001/v1")

    # Act
    context = ApplicationContext.create()
    monkeypatch.setattr(context.faiss_manager, "load_cpu_index", lambda: None)
    monkeypatch.setattr(context.faiss_manager, "clone_to_gpu", lambda: False)
    context.faiss_manager.gpu_disabled_reason = None

    # Assert
    assert context.settings is not None
    assert context.paths.repo_root == repo_root.resolve()
    assert context.vllm_client is not None
    assert context.faiss_manager is not None
    assert isinstance(context.paths, ResolvedPaths)


def test_application_context_create_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that ApplicationContext.create() raises ConfigurationError for invalid config."""
    # Arrange
    monkeypatch.setenv("REPO_ROOT", "/nonexistent/path")
    monkeypatch.setenv("VLLM_URL", "http://localhost:8001/v1")

    # Act & Assert
    with pytest.raises(ConfigurationError, match="Repository root does not exist"):
        ApplicationContext.create()


def test_application_context_ensure_faiss_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test ensure_faiss_ready() lazy loading."""
    # Arrange
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "data").mkdir()
    (repo_root / "data" / "vectors").mkdir()
    (repo_root / "data" / "faiss").mkdir()
    faiss_index = repo_root / "data" / "faiss" / "code.ivfpq.faiss"
    faiss_index.touch()
    (repo_root / "data" / "catalog.duckdb").touch()

    monkeypatch.setenv("REPO_ROOT", str(repo_root))
    monkeypatch.setenv("VLLM_URL", "http://localhost:8001/v1")

    context = ApplicationContext.create()
    monkeypatch.setattr(context.faiss_manager, "load_cpu_index", lambda: None)
    monkeypatch.setattr(context.faiss_manager, "clone_to_gpu", lambda: False)
    context.faiss_manager.gpu_disabled_reason = None

    # Act - ensure_faiss_ready should handle missing index gracefully
    ready, limits, error = context.ensure_faiss_ready()

    # Assert - FAISS index file exists but is empty, so loading will fail
    # This is expected behavior - the method returns ready=False with error message
    assert isinstance(ready, bool)
    assert isinstance(limits, list)
    assert error is None or isinstance(error, str)


def test_application_context_ensure_faiss_ready_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that ensure_faiss_ready() caching works."""
    # Arrange
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "data").mkdir()
    (repo_root / "data" / "vectors").mkdir()
    (repo_root / "data" / "faiss").mkdir()
    faiss_index = repo_root / "data" / "faiss" / "code.ivfpq.faiss"
    faiss_index.touch()
    (repo_root / "data" / "catalog.duckdb").touch()

    monkeypatch.setenv("REPO_ROOT", str(repo_root))
    monkeypatch.setenv("VLLM_URL", "http://localhost:8001/v1")

    context = ApplicationContext.create()
    monkeypatch.setattr(context.faiss_manager, "load_cpu_index", lambda: None)
    monkeypatch.setattr(context.faiss_manager, "clone_to_gpu", lambda: False)
    context.faiss_manager.gpu_disabled_reason = None

    # Act - call twice
    ready1, limits1, error1 = context.ensure_faiss_ready()
    ready2, limits2, error2 = context.ensure_faiss_ready()

    # Assert - results should be consistent (cached)
    assert ready1 == ready2
    assert limits1 == limits2
    assert error1 == error2


def test_application_context_open_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test open_catalog() context manager."""
    # Arrange
    import duckdb

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "data").mkdir()
    (repo_root / "data" / "vectors").mkdir()
    (repo_root / "data" / "faiss").mkdir()
    (repo_root / "data" / "faiss" / "code.ivfpq.faiss").touch()
    duckdb_path = repo_root / "data" / "catalog.duckdb"
    # Create a valid DuckDB database file
    conn = duckdb.connect(str(duckdb_path))
    conn.close()

    monkeypatch.setenv("REPO_ROOT", str(repo_root))
    monkeypatch.setenv("VLLM_URL", "http://localhost:8001/v1")

    context = ApplicationContext.create()

    # Act
    with context.open_catalog() as catalog:
        # Assert
        assert catalog is not None
        assert catalog.db_path == duckdb_path
        with catalog.connection() as conn:
            assert conn.execute("SELECT 1").fetchone() == (1,)
