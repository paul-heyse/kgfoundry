"""Shared pytest fixtures for codeintel_rev tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from codeintel_rev.app.config_context import ApplicationContext, ResolvedPaths
from codeintel_rev.app.scope_registry import ScopeRegistry
from codeintel_rev.config.settings import (
    IndexConfig,
    PathsConfig,
    ServerLimits,
    Settings,
    VLLMConfig,
)
from codeintel_rev.io.faiss_manager import FAISSManager
from codeintel_rev.io.git_client import AsyncGitClient, GitClient
from codeintel_rev.io.vllm_client import VLLMClient


@pytest.fixture
def mock_application_context(tmp_path: Path) -> ApplicationContext:
    """Create a mock ApplicationContext for testing.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory fixture.

    Returns
    -------
    ApplicationContext
        Mock application context with minimal required attributes.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    # Create minimal settings
    settings = Settings(
        paths=PathsConfig(
            repo_root=str(repo_root),
            data_dir="data",
            vectors_dir="data/vectors",
            faiss_index="data/faiss/index.faiss",
            duckdb_path="data/catalog.duckdb",
            scip_index="index.scip.json",
        ),
        index=IndexConfig(
            vec_dim=2560,
            chunk_budget=2200,
            faiss_nlist=8192,
            use_cuvs=True,
        ),
        vllm=VLLMConfig(
            base_url="http://localhost:8001/v1",
            batch_size=32,
        ),
        limits=ServerLimits(),
    )

    # Create resolved paths
    paths = ResolvedPaths(
        repo_root=repo_root,
        data_dir=repo_root / "data",
        vectors_dir=repo_root / "data" / "vectors",
        faiss_index=repo_root / "data" / "faiss" / "index.faiss",
        duckdb_path=repo_root / "data" / "catalog.duckdb",
        scip_index=repo_root / "index.scip.json",
    )

    # Create mock clients
    vllm_client = MagicMock(spec=VLLMClient)
    faiss_manager = MagicMock(spec=FAISSManager)
    git_client = MagicMock(spec=GitClient)
    async_git_client = MagicMock(spec=AsyncGitClient)
    scope_registry = ScopeRegistry()

    return ApplicationContext(
        settings=settings,
        paths=paths,
        vllm_client=vllm_client,
        faiss_manager=faiss_manager,
        scope_registry=scope_registry,
        git_client=git_client,
        async_git_client=async_git_client,
    )
