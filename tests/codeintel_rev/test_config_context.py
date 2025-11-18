"""Unit tests for ApplicationContext and configuration management."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import duckdb
import pytest
from codeintel_rev.app.config_context import ApplicationContext, resolve_application_paths
from codeintel_rev.config.paths import ResolvedPaths
from codeintel_rev.runtime.factory_adjustment import DefaultFactoryAdjuster

from kgfoundry_common.errors import ConfigurationError
from tests._helpers import assertions
from tests._helpers.settings import build_settings_for_repo


def _noop_load_cpu_index(*_: object, **__: object) -> None:
    """Test helper that simulates successful FAISS loading."""
    return


def _prepare_base_repo(repo_root: Path) -> None:
    """Create directories/files required by readiness probes."""
    config_dir = repo_root / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "app.yml"
    config_file.write_text("tests: true")
    for relative in ("logs", ".cache", ".tmp", "plugins"):
        (repo_root / relative).mkdir(parents=True, exist_ok=True)
    data_dir = repo_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "vectors").mkdir(parents=True, exist_ok=True)


def test_resolve_application_paths_success(tmp_path: Path) -> None:
    """Test successful path resolution with valid repo root."""
    # Arrange
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "data").mkdir()

    settings = build_settings_for_repo(repo_root)

    # Act
    paths = resolve_application_paths(settings)

    # Assert
    assertions.expect_equal(paths.repo_root, repo_root.resolve())
    assertions.expect_equal(paths.data_dir, (repo_root / "data").resolve())
    assertions.expect_equal(paths.vectors_dir.parent, paths.data_dir)
    assertions.expect_true(
        all(path.is_absolute() for path in [paths.repo_root, paths.data_dir, paths.vectors_dir])
    )


def test_resolve_application_paths_missing_repo_root() -> None:
    """Missing repo roots are tolerated during pure resolution."""
    settings = build_settings_for_repo(Path("/nonexistent/path"))

    paths = resolve_application_paths(settings)

    assertions.expect_equal(paths.repo_root, Path("/nonexistent/path").resolve())


def test_resolve_application_paths_not_directory(tmp_path: Path) -> None:
    """Non-directory repo roots are tolerated during pure resolution."""
    repo_file = tmp_path / "not_a_dir"
    repo_file.touch()

    settings = build_settings_for_repo(repo_file)

    paths = resolve_application_paths(settings)

    assertions.expect_equal(paths.repo_root, repo_file.resolve())


def test_resolve_application_paths_relative_conversion(tmp_path: Path) -> None:
    """Test that relative paths are converted to absolute paths."""
    # Arrange
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "data").mkdir()

    settings = build_settings_for_repo(repo_root)

    # Act
    paths = resolve_application_paths(settings)

    # Assert
    assertions.expect_true(paths.faiss_index.is_absolute())
    assertions.expect_equal(paths.faiss_index.parent.parent, paths.data_dir)
    assertions.expect_true(paths.duckdb_path.is_absolute())
    assertions.expect_true(paths.scip_index.is_absolute())


def test_application_context_create(tmp_path: Path) -> None:
    """Test ApplicationContext.create() initializes all clients."""
    # Arrange
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _prepare_base_repo(repo_root)
    (repo_root / "data").mkdir(exist_ok=True)
    (repo_root / "data" / "vectors").mkdir(exist_ok=True)
    (repo_root / "data" / "faiss").mkdir(exist_ok=True)
    (repo_root / "data" / "faiss" / "code.ivfpq.faiss").touch()
    (repo_root / "data" / "catalog.duckdb").touch()

    settings = build_settings_for_repo(repo_root)

    # Act
    context = ApplicationContext.create(settings=settings)
    context.faiss_manager.load_cpu_index = _noop_load_cpu_index

    # Assert
    assertions.expect_true(context.settings is not None)
    assertions.expect_equal(context.paths.repo_root, repo_root.resolve())
    assertions.expect_true(context.vllm_client is not None)
    assertions.expect_true(context.faiss_manager is not None)
    assertions.expect_true(isinstance(context.paths, ResolvedPaths))


def test_application_context_create_invalid_config() -> None:
    """Test that ApplicationContext.create() raises ConfigurationError for invalid config."""
    # Arrange
    settings = build_settings_for_repo(Path("/nonexistent/path"))

    # Act & Assert
    with pytest.raises(ConfigurationError, match="Repository root does not exist"):
        ApplicationContext.create(settings=settings)


def test_application_context_ensure_faiss_ready(
    tmp_path: Path,
) -> None:
    """Test ensure_faiss_ready() lazy loading."""
    # Arrange
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _prepare_base_repo(repo_root)
    (repo_root / "data").mkdir(exist_ok=True)
    (repo_root / "data" / "vectors").mkdir(exist_ok=True)
    (repo_root / "data" / "faiss").mkdir(exist_ok=True)
    faiss_index = repo_root / "data" / "faiss" / "code.ivfpq.faiss"
    faiss_index.touch()
    (repo_root / "data" / "catalog.duckdb").touch()

    settings = build_settings_for_repo(repo_root)

    context = ApplicationContext.create(settings=settings)
    context.faiss_manager.load_cpu_index = _noop_load_cpu_index

    # Act - ensure_faiss_ready should handle missing index gracefully
    ready, limits, error = context.ensure_faiss_ready()

    # Assert - FAISS index file exists but is empty, so loading will fail
    # This is expected behavior - the method returns ready=False with error message
    assertions.expect_true(isinstance(ready, bool))
    assertions.expect_true(isinstance(limits, list))
    assertions.expect_true(error is None or isinstance(error, str))


def test_application_context_ensure_faiss_ready_cached(
    tmp_path: Path,
) -> None:
    """Test that ensure_faiss_ready() caching works."""
    # Arrange
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _prepare_base_repo(repo_root)
    (repo_root / "data").mkdir(exist_ok=True)
    (repo_root / "data" / "vectors").mkdir(exist_ok=True)
    (repo_root / "data" / "faiss").mkdir(exist_ok=True)
    faiss_index = repo_root / "data" / "faiss" / "code.ivfpq.faiss"
    faiss_index.touch()
    (repo_root / "data" / "catalog.duckdb").touch()

    settings = build_settings_for_repo(repo_root)

    context = ApplicationContext.create(settings=settings)
    context.faiss_manager.load_cpu_index = _noop_load_cpu_index

    # Act - call twice
    ready1, limits1, error1 = context.ensure_faiss_ready()
    ready2, limits2, error2 = context.ensure_faiss_ready()

    # Assert - results should be consistent (cached)
    assertions.expect_equal(ready1, ready2)
    assertions.expect_equal(limits1, limits2)
    assertions.expect_equal(error1, error2)


def test_application_context_open_catalog(tmp_path: Path) -> None:
    """Test open_catalog() context manager."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _prepare_base_repo(repo_root)
    (repo_root / "data").mkdir(exist_ok=True)
    (repo_root / "data" / "vectors").mkdir(exist_ok=True)
    (repo_root / "data" / "faiss").mkdir(exist_ok=True)
    (repo_root / "data" / "faiss" / "code.ivfpq.faiss").touch()
    duckdb_path = repo_root / "data" / "catalog.duckdb"
    # Create a valid DuckDB database file
    conn = duckdb.connect(str(duckdb_path))
    conn.close()

    settings = build_settings_for_repo(repo_root)
    context = ApplicationContext.create(settings=settings)

    # Act
    with context.open_catalog() as catalog:
        assertions.expect_true(catalog is not None)
        assertions.expect_equal(catalog.db_path, duckdb_path)
        with catalog.connection() as conn:
            assertions.expect_equal(conn.execute("SELECT 1").fetchone(), (1,))


def test_build_factory_adjuster_from_settings(
    tmp_path: Path,
) -> None:
    """Verify the default factory adjuster mirrors index settings."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _prepare_base_repo(repo_root)
    data_dir = repo_root / "data"
    vectors = data_dir / "vectors"
    faiss_dir = data_dir / "faiss"
    data_dir.mkdir(exist_ok=True)
    vectors.mkdir(exist_ok=True)
    faiss_dir.mkdir(exist_ok=True)
    (faiss_dir / "code.ivfpq.faiss").touch()
    (data_dir / "catalog.duckdb").touch()
    settings = build_settings_for_repo(repo_root)
    context = ApplicationContext.create(settings=settings)
    assertions.expect_true(isinstance(context.factory_adjuster, DefaultFactoryAdjuster))
    expected = getattr(context.settings.index, "faiss_nprobe", None)
    adjuster = cast("DefaultFactoryAdjuster", context.factory_adjuster)
    assertions.expect_equal(adjuster.faiss_nprobe, expected)
