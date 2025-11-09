"""Tests for service context path resolution helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
from codeintel_rev.app import config_context
from codeintel_rev.mcp_server import service_context


class RecordingFAISSManager:
    """Stub FAISS manager capturing constructor arguments."""

    def __init__(
        self,
        *,
        index_path: Path,
        vec_dim: int,
        nlist: int,
        use_cuvs: bool,
    ) -> None:
        self.index_path = index_path
        self.vec_dim = vec_dim
        self.nlist = nlist
        self.use_cuvs = use_cuvs
        self.cpu_index = None
        self.gpu_index = None
        self.gpu_resources = None
        self.gpu_disabled_reason = None
        self.load_calls = 0
        self.clone_calls = 0

    def load_cpu_index(self) -> None:
        """Record CPU index load attempts."""
        self.load_calls += 1

    def clone_to_gpu(self) -> bool:
        """Record GPU clone attempts and report disabled GPU.

        Returns
        -------
        bool
            Always returns False to indicate GPU is disabled.
        """
        self.clone_calls += 1
        return False


class RecordingDuckDBCatalog:
    """Stub DuckDB catalog capturing constructor arguments."""

    def __init__(self, db_path: Path, vectors_dir: Path, **_: object) -> None:
        self.db_path = db_path
        self.vectors_dir = vectors_dir
        self.open_called = False
        self.closed = False

    def open(self) -> None:  # pragma: no cover - trivial shim
        """Record catalog opening."""
        self.open_called = True

    def close(self) -> None:  # pragma: no cover - trivial shim
        """Record catalog closing."""
        self.closed = True


class DummyVLLMClient:
    """Minimal vLLM client placeholder used for dependency injection."""

    def __init__(self, _config: object) -> None:  # pragma: no cover - trivial shim
        return


def test_service_context_resolves_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Relative configuration paths resolve against ``REPO_ROOT``."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    faiss_rel = "indexes/code.ivfpq.faiss"
    duckdb_rel = "catalog/catalog.duckdb"
    vectors_rel = "artifacts/vectors"

    monkeypatch.setenv("REPO_ROOT", str(repo_root))
    monkeypatch.setenv("FAISS_INDEX", faiss_rel)
    monkeypatch.setenv("DUCKDB_PATH", duckdb_rel)
    monkeypatch.setenv("VECTORS_DIR", vectors_rel)

    expected_faiss_path = (repo_root / faiss_rel).resolve()
    expected_duckdb_path = (repo_root / duckdb_rel).resolve()
    expected_vectors_dir = (repo_root / vectors_rel).resolve()

    expected_faiss_path.parent.mkdir(parents=True, exist_ok=True)
    expected_faiss_path.touch()
    expected_vectors_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config_context, "FAISSManager", RecordingFAISSManager)
    monkeypatch.setattr(config_context, "DuckDBCatalog", RecordingDuckDBCatalog)
    monkeypatch.setattr(config_context, "VLLMClient", DummyVLLMClient)

    service_context.reset_service_context()

    context = service_context.get_service_context()

    if not isinstance(context.faiss_manager, RecordingFAISSManager):
        pytest.fail("Expected RecordingFAISSManager")
    if context.faiss_manager.index_path != expected_faiss_path:
        pytest.fail(
            f"Expected index_path {expected_faiss_path}, got {context.faiss_manager.index_path}"
        )

    ready, limits, error = context.ensure_faiss_ready()

    if ready is not True:
        pytest.fail("Expected ready to be True")
    if limits != []:
        pytest.fail(f"Expected empty limits, got {limits}")
    if error is not None:
        pytest.fail(f"Expected no error, got {error}")
    if context.faiss_manager.load_calls != 1:
        pytest.fail(f"Expected 1 load call, got {context.faiss_manager.load_calls}")
    if context.faiss_manager.clone_calls != 1:
        pytest.fail(f"Expected 1 clone call, got {context.faiss_manager.clone_calls}")

    with context.open_catalog() as catalog:
        if not isinstance(catalog, RecordingDuckDBCatalog):
            pytest.fail("Expected RecordingDuckDBCatalog")
        if catalog.db_path != expected_duckdb_path:
            pytest.fail(f"Expected db_path {expected_duckdb_path}, got {catalog.db_path}")
        if catalog.vectors_dir != expected_vectors_dir:
            pytest.fail(f"Expected vectors_dir {expected_vectors_dir}, got {catalog.vectors_dir}")
        if catalog.open_called is not True:
            pytest.fail("Expected open_called to be True")

    if catalog.closed is not True:
        pytest.fail("Expected catalog to be closed")

    service_context.reset_service_context()
