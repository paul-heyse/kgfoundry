"""Shared pytest fixtures for codeintel_rev tests."""

from __future__ import annotations

import os
import time as time_module
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
from codeintel_rev.config.paths import ResolvedPaths, resolve_application_paths
from codeintel_rev.config.shim import settings_from_app_config
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.io.duckdb_manager import DuckDBConfig, DuckDBManager
from codeintel_rev.io.faiss_manager import FAISSManager
from codeintel_rev.io.git_client import AsyncGitClient, GitClient
from codeintel_rev.io.vllm_client import VLLMClient

from tests._helpers.settings import build_app_config_for_repo

# Import for side effects: ensures FAISS stub is registered


class _FakeRedis:
    """Simple in-memory Redis mimic for tests."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[bytes, float | None]] = {}

    async def get(self, name: str) -> bytes | None:
        record = self._data.get(name)
        if record is None:
            return None
        value, expires_at = record
        if expires_at is not None and expires_at <= time_module.monotonic():
            self._data.pop(name, None)
            return None
        return value

    async def setex(self, name: str, time: int, value: bytes) -> bool | None:
        expires_at = time_module.monotonic() + time if time > 0 else None
        self._data[name] = (value, expires_at)
        return True

    async def set(self, name: str, value: bytes) -> bool | None:
        self._data[name] = (value, None)
        return True

    async def delete(self, *names: str) -> int | None:
        removed = 0
        for entry in names:
            if self._data.pop(entry, None) is not None:
                removed += 1
        return removed

    async def close(self) -> None:
        self._data.clear()


def _default_duckdb_catalog_factory(
    resolved: ResolvedPaths,
    _settings: object,
    manager: DuckDBManager,
) -> DuckDBCatalog:
    """Construct a DuckDB catalog for tests.

    Returns
    -------
    DuckDBCatalog
        DuckDB catalog instance configured for testing.
    """
    catalog = DuckDBCatalog(
        resolved.duckdb_path,
        resolved.vectors_dir,
        materialize=False,
        manager=manager,
        log_queries=False,
        repo_root=resolved.repo_root,
    )
    catalog.set_idmap_path(resolved.faiss_idmap_path)
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
        Mock application context with test paths and settings.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    app_config = build_app_config_for_repo(repo_root)
    paths = resolve_application_paths(app_config)
    settings = settings_from_app_config(app_config)

    paths.data_dir.mkdir(parents=True, exist_ok=True)
    paths.vectors_dir.mkdir(parents=True, exist_ok=True)
    paths.faiss_index.parent.mkdir(parents=True, exist_ok=True)
    paths.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    paths.xtr_dir.mkdir(parents=True, exist_ok=True)
    paths.faiss_index.touch()
    paths.faiss_idmap_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(paths.duckdb_path)):
        pass

    vllm_client = MagicMock(spec=VLLMClient)
    vllm_client.embed_batch.return_value = np.zeros(
        (1, settings.vllm.embedding_dim),
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
    redis_client = _FakeRedis()
    scope_store = ScopeStore(
        redis_client,
        l1_maxsize=settings.redis.scope_l1_size,
        l1_ttl_seconds=settings.redis.scope_l1_ttl_seconds,
        l2_ttl_seconds=settings.redis.scope_l2_ttl_seconds,
    )
    duckdb_manager = DuckDBManager(paths.duckdb_path, DuckDBConfig())

    return ApplicationContext(
        app_config=app_config,
        settings=settings,
        paths=paths,
        vllm_client=vllm_client,
        faiss_manager=faiss_manager,
        scope_store=scope_store,
        duckdb_manager=duckdb_manager,
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
