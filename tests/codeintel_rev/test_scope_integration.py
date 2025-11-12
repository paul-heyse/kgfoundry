from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from codeintel_rev.app.config_context import ApplicationContext, ResolvedPaths
from codeintel_rev.app.middleware import session_id_var
from codeintel_rev.app.scope_store import ScopeStore
from codeintel_rev.config.settings import (
    BM25Config,
    CodeRankConfig,
    CodeRankLLMConfig,
    EvalConfig,
    IndexConfig,
    PathsConfig,
    RedisConfig,
    RerankConfig,
    ServerLimits,
    Settings,
    SpladeConfig,
    VLLMConfig,
    WarpConfig,
    XTRConfig,
)
from codeintel_rev.io.duckdb_manager import DuckDBConfig, DuckDBManager
from codeintel_rev.io.faiss_manager import FAISSManager
from codeintel_rev.io.git_client import AsyncGitClient, GitClient
from codeintel_rev.io.vllm_client import VLLMClient
from codeintel_rev.mcp_server.adapters import files as files_adapter
from codeintel_rev.mcp_server.schemas import ScopeIn
from codeintel_rev.mcp_server.scope_utils import merge_scope_filters


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
    settings = Settings(
        paths=PathsConfig(
            repo_root=str(repo_root),
            data_dir="data",
            vectors_dir="data/vectors",
            faiss_index="data/faiss/index.faiss",
            duckdb_path="data/catalog.duckdb",
            scip_index="index.scip.json",
            coderank_vectors_dir="data/coderank_vectors",
            coderank_faiss_index="data/faiss/coderank.faiss",
            warp_index_dir="indexes/warp_xtr",
            xtr_dir="data/xtr",
        ),
        index=IndexConfig(vec_dim=2560, chunk_budget=2200, faiss_nlist=8192, use_cuvs=True),
        vllm=VLLMConfig(base_url="http://localhost:8001/v1", batch_size=32),
        limits=ServerLimits(),
        eval=EvalConfig(),
        redis=RedisConfig(
            url="redis://127.0.0.1:6379/0",
            scope_l1_size=64,
            scope_l1_ttl_seconds=300,
            scope_l2_ttl_seconds=3600,
        ),
        duckdb=DuckDBConfig(),
        bm25=BM25Config(),
        splade=SpladeConfig(),
        coderank=CodeRankConfig(),
        warp=WarpConfig(),
        xtr=XTRConfig(),
        rerank=RerankConfig(),
        coderank_llm=CodeRankLLMConfig(),
    )

    paths = ResolvedPaths(
        repo_root=repo_root,
        data_dir=repo_root / "data",
        vectors_dir=repo_root / "data" / "vectors",
        faiss_index=repo_root / "data" / "faiss" / "index.faiss",
        faiss_idmap_path=repo_root / "data" / "faiss" / "faiss_idmap.parquet",
        duckdb_path=repo_root / "data" / "catalog.duckdb",
        scip_index=repo_root / "index.scip.json",
        coderank_vectors_dir=repo_root / "data" / "coderank_vectors",
        coderank_faiss_index=repo_root / "data" / "faiss" / "coderank.faiss",
        warp_index_dir=repo_root / "indexes" / "warp_xtr",
        xtr_dir=repo_root / "data" / "xtr",
    )

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
        l1_maxsize=settings.redis.scope_l1_size,
        l1_ttl_seconds=settings.redis.scope_l1_ttl_seconds,
        l2_ttl_seconds=settings.redis.scope_l2_ttl_seconds,
    )

    duckdb_manager = DuckDBManager(paths.duckdb_path, DuckDBConfig())

    vllm_client = MagicMock(spec=VLLMClient)
    faiss_manager = MagicMock(spec=FAISSManager)
    faiss_manager.gpu_index = None
    faiss_manager.gpu_disabled_reason = None
    git_client = MagicMock(spec=GitClient)
    async_git_client = AsyncMock(spec=AsyncGitClient)

    return ApplicationContext(
        settings=settings,
        paths=paths,
        vllm_client=vllm_client,
        faiss_manager=faiss_manager,
        scope_store=scope_store,
        duckdb_manager=duckdb_manager,
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
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    context = _build_context(repo_root)

    scope: ScopeIn = cast("ScopeIn", {"include_globs": ["src/**"], "languages": ["python"]})
    await files_adapter.set_scope(context, scope)

    stored = await context.scope_store.get(mock_session_id)
    assert stored == scope


@pytest.mark.asyncio
async def test_list_paths_honours_scope_filters(tmp_path: Path, mock_session_id: str) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _write_repo(repo_root)
    context = _build_context(repo_root)

    scope: ScopeIn = cast("ScopeIn", {"include_globs": ["src/**"], "languages": []})
    assert session_id_var.get() == mock_session_id

    await files_adapter.set_scope(context, scope)

    result = await files_adapter.list_paths(context, max_results=100)
    paths = {item["path"] for item in result["items"]}
    assert all(path.startswith("src/") for path in paths), f"paths={sorted(paths)}"


def test_merge_scope_filters_precedence() -> None:
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
    assert merged["include_globs"] == ["docs/**"]
    assert merged["languages"] == ["markdown"]
