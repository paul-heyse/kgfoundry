"""Tests for scope integration: persistence, filtering, and scope store operations."""

from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
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
from codeintel_rev.mcp_server.adapters import files as files_adapter
from codeintel_rev.mcp_server.schemas import ScopeIn
from codeintel_rev.mcp_server.scope_utils import merge_scope_filters

from tests._helpers import assertions
from tests._helpers.settings import build_app_config_for_repo


class _FakeRedis:
    """Simple in-memory Redis mimic for tests."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    async def get(self, name: str) -> bytes | None:
        return self._data.get(name)

    async def setex(self, name: str, time: int, value: bytes) -> bool | None:
        _ = time
        self._data[name] = value
        return True

    async def set(self, name: str, value: bytes) -> bool | None:
        self._data[name] = value
        return True

    async def delete(self, *names: str) -> int | None:
        removed = 0
        for entry in names:
            if self._data.pop(entry, None) is not None:
                removed += 1
        return removed

    async def close(self) -> None:
        self._data.clear()


def _build_context(repo_root: Path) -> ApplicationContext:
    app_config = build_app_config_for_repo(repo_root)
    paths = resolve_application_paths(app_config)
    settings = settings_from_app_config(app_config)

    paths.data_dir.mkdir(parents=True, exist_ok=True)
    paths.vectors_dir.mkdir(parents=True, exist_ok=True)
    paths.faiss_index.parent.mkdir(parents=True, exist_ok=True)
    paths.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    paths.coderank_vectors_dir.mkdir(parents=True, exist_ok=True)
    paths.coderank_faiss_index.parent.mkdir(parents=True, exist_ok=True)
    paths.warp_index_dir.mkdir(parents=True, exist_ok=True)
    paths.xtr_dir.mkdir(parents=True, exist_ok=True)

    scope_store = ScopeStore(
        _FakeRedis(),
        l1_maxsize=app_config.redis.scope_l1_size,
        l1_ttl_seconds=app_config.redis.scope_l1_ttl_seconds,
        l2_ttl_seconds=app_config.redis.scope_l2_ttl_seconds,
    )

    duckdb_manager = DuckDBManager(paths.duckdb_path, DuckDBConfig())

    vllm_client = MagicMock(spec=VLLMClient)
    faiss_manager = MagicMock(spec=FAISSManager)
    git_client = MagicMock(spec=GitClient)
    async_git_client = AsyncMock(spec=AsyncGitClient)

    def _duckdb_catalog_factory(
        resolved: ResolvedPaths,
        _cfg: object,
        manager: DuckDBManager,
    ) -> DuckDBCatalog:
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

    return ApplicationContext(
        app_config=app_config,
        settings=settings,
        paths=paths,
        vllm_client=vllm_client,
        faiss_manager=faiss_manager,
        scope_store=scope_store,
        duckdb_manager=duckdb_manager,
        duckdb_catalog_factory=_duckdb_catalog_factory,
        git_client=git_client,
        async_git_client=async_git_client,
    )


def _write_repo(repo_root: Path) -> None:
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "tests").mkdir(parents=True, exist_ok=True)
    (repo_root / "docs").mkdir(parents=True, exist_ok=True)

    (repo_root / "src" / "main.py").write_text("def main():\n    return 42\n")
    (repo_root / "src" / "util.py").write_text("def util():\n    return None\n")
    (repo_root / "tests" / "test_main.py").write_text("def test_main():\n    assert True\n")
    (repo_root / "docs" / "README.md").write_text("# Documentation\n")


@pytest.mark.asyncio
async def test_set_scope_persists_in_store(tmp_path: Path, mock_session_id: str) -> None:
    """Test that set_scope persists scope data in the scope store."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    context = _build_context(repo_root)

    scope: ScopeIn = cast("ScopeIn", {"include_globs": ["src/**"], "languages": ["python"]})
    await files_adapter.set_scope(context, scope)

    stored = await context.scope_store.get(mock_session_id)
    assertions.expect_equal(stored, scope)


@pytest.mark.asyncio
async def test_list_paths_honours_scope_filters(tmp_path: Path, mock_session_id: str) -> None:
    """Test that list_paths respects scope filters (include_globs, languages)."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo(repo_root)
    context = _build_context(repo_root)

    scope: ScopeIn = cast("ScopeIn", {"include_globs": ["src/**"], "languages": []})
    assertions.expect_equal(session_id_var.get(), mock_session_id)

    await files_adapter.set_scope(context, scope)

    result = await files_adapter.list_paths(context, max_results=100)
    paths = {item["path"] for item in result["items"]}
    assertions.expect_true(
        all(path.startswith("src/") for path in paths), reason=f"paths={sorted(paths)}"
    )


def test_merge_scope_filters_precedence() -> None:
    """Test that merge_scope_filters applies filters with correct precedence."""
    scope: ScopeIn = cast(
        "ScopeIn",
        {
            "include_globs": ["src/**"],
            "exclude_globs": ["**/tests/**"],
            "languages": ["python"],
        },
    )
    explicit = {"include_globs": ["docs/**"], "languages": ["markdown"]}
    merged = merge_scope_filters(scope, explicit)
    assertions.expect_equal(merged["include_globs"], ["docs/**"])
    assertions.expect_equal(merged["languages"], ["markdown"])
