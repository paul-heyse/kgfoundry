"""Shared pytest fixtures for codeintel_rev tests."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import duckdb
import numpy as np
import pytest

os.environ.setdefault("FAISS_OPT_LEVEL", "generic")

from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.app.middleware import session_id_var
from codeintel_rev.app.scope_store import ScopeStore
from codeintel_rev.config.paths import resolve_application_paths
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, DuckDBCatalogConfig
from codeintel_rev.io.duckdb_manager import DuckDBConfig, DuckDBManager
from codeintel_rev.io.faiss_manager import FAISSManager
from codeintel_rev.io.git_client import AsyncGitClient, GitClient
from codeintel_rev.io.vllm_client import VLLMClient

from tests._helpers.adapters import InMemoryScopeStore
from tests._helpers.settings import build_app_config_for_repo

# Import for side effects: ensures FAISS stub is registered


def _default_duckdb_catalog_factory(
    catalog_cfg: DuckDBCatalogConfig,
    manager: DuckDBManager,
) -> DuckDBCatalog:
    """Construct a DuckDB catalog for tests.

    Returns
    -------
    DuckDBCatalog
        DuckDB catalog instance configured for testing.
    """
    catalog = DuckDBCatalog(
        catalog_cfg.db_path,
        catalog_cfg.vectors_dir,
        materialize=catalog_cfg.materialize,
        manager=manager,
        log_queries=catalog_cfg.log_queries,
        repo_root=catalog_cfg.repo_root,
    )
    catalog.set_idmap_path(catalog_cfg.idmap_path)
    return catalog


@pytest.fixture
def mock_application_context(tmp_path: Path) -> ApplicationContext:
    """Create a mock ApplicationContext for testing.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory path provided by pytest fixture.

    Returns
    -------
    ApplicationContext
        Mock application context with test paths and configuration.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    app_config = build_app_config_for_repo(repo_root)
    paths = resolve_application_paths(app_config)

    paths.data_dir.mkdir(parents=True, exist_ok=True)
    paths.vectors_dir.mkdir(parents=True, exist_ok=True)
    paths.faiss_index.parent.mkdir(parents=True, exist_ok=True)
    paths.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    paths.xtr_dir.mkdir(parents=True, exist_ok=True)
    paths.faiss_index.touch()
    paths.faiss_idmap_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_cfg = DuckDBCatalogConfig(
        db_path=paths.duckdb_path,
        vectors_dir=paths.vectors_dir,
        repo_root=paths.repo_root,
        idmap_path=paths.faiss_idmap_path,
        materialize=app_config.index.duckdb_materialize,
        log_queries=False,
    )
    with duckdb.connect(str(paths.duckdb_path)):
        pass

    vllm_client = MagicMock(spec=VLLMClient)
    vllm_client.embed_batch.return_value = np.zeros(
        (1, app_config.vllm.embedding_dim),
        dtype=np.float32,
    )
    faiss_manager = MagicMock(spec=FAISSManager)
    # ApplicationContext.ensure_faiss_ready touches tuning paths on the FAISS manager.
    faiss_manager.autotune_profile_path = paths.faiss_index.with_name("tuning.json")
    git_client = MagicMock(spec=GitClient)
    async_git_client = AsyncMock(spec=AsyncGitClient)
    async_git_client.blame_range.return_value = [
        {
            "line": 1,
            "commit": "abc1234",
            "author": "Test Author",
            "date": "2024-01-01T00:00:00Z",
            "message": "Test commit",
        }
    ]
    async_git_client.file_history.return_value = [
        {
            "sha": "abc1234",
            "full_sha": "abc1234abcdef",
            "author": "Test Author",
            "email": "test@example.com",
            "date": "2024-01-01T00:00:00Z",
            "message": "Test commit",
        }
    ]
    scope_store = ScopeStore(
        scope_store_backend,
        l1_maxsize=app_config.redis.scope_l1_size,
        l1_ttl_seconds=app_config.redis.scope_l1_ttl_seconds,
        l2_ttl_seconds=app_config.redis.scope_l2_ttl_seconds,
    )
    duckdb_manager = DuckDBManager(paths.duckdb_path, DuckDBConfig())

    return ApplicationContext(
        app_config=app_config,
        paths=paths,
        vllm_client=vllm_client,
        faiss_manager=faiss_manager,
        scope_store=scope_store,
        duckdb_manager=duckdb_manager,
        catalog_config=catalog_cfg,
        duckdb_catalog_factory=_default_duckdb_catalog_factory,
        git_client=git_client,
        async_git_client=async_git_client,
    )


@pytest.fixture
def mock_session_id() -> Iterator[str]:
    """Provide a session ID bound to middleware context vars for adapter calls.

    Yields
    ------
    str
        Session ID string that is set in the middleware context variable.
        The context variable is reset after the test completes.
    """
    session_id = "test-session"
    token = session_id_var.set(session_id)
    try:
        yield session_id
    finally:
        session_id_var.reset(token)


@pytest.fixture(autouse=True)
def _auto_session_id() -> Iterator[None]:
    """Ensure a session ID is always present for tests that omit the fixture."""
    token = session_id_var.set("auto-session")
    try:
        yield
    finally:
        session_id_var.reset(token)
