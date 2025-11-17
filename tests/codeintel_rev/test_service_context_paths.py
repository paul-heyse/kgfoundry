"""Tests for service context path resolution helpers."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from codeintel_rev.app import config_context
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.mcp_server import service_context

from tests._helpers import assertions


class RecordingFAISSManager:
    """Stub FAISS manager capturing constructor arguments."""

    def __init__(
        self,
        *,
        index_path: Path,
        vec_dim: int,
        nlist: int,
        runtime: object | None = None,
    ) -> None:
        self.index_path = index_path
        self.vec_dim = vec_dim
        self.nlist = nlist
        self.cpu_index = None
        self.load_calls = 0
        self.runtime = runtime
        self.autotune_profile_path = index_path.with_name("tuning.json")

    def load_cpu_index(self, *_: object, **__: object) -> None:
        """Record CPU index load attempts."""
        self.load_calls += 1

    @staticmethod
    def get_compile_options() -> dict[str, str]:
        """Return fake compile options for logging.

        Returns
        -------
        dict[str, str]
            Static compile option payload for assertions.
        """
        return {"arch": "stub"}


class RecordingDuckDBCatalog:
    """Stub DuckDB catalog capturing constructor arguments."""

    def __init__(self, db_path: Path, vectors_dir: Path, **_: object) -> None:
        self.db_path = db_path
        self.vectors_dir = vectors_dir
        self.open_called = False
        self.closed = False
        self.idmap_path: Path | None = None

    def open(self) -> None:  # pragma: no cover - trivial shim
        """Record catalog opening."""
        self.open_called = True

    def close(self) -> None:  # pragma: no cover - trivial shim
        """Record catalog closing."""
        self.closed = True

    def set_idmap_path(self, path: Path) -> None:
        """Record configured FAISS ID map path."""
        self.idmap_path = path


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

    monkeypatch.setattr(config_context, "_import_faiss_manager_cls", lambda: RecordingFAISSManager)
    monkeypatch.setattr(config_context, "DuckDBCatalog", RecordingDuckDBCatalog)
    monkeypatch.setattr(config_context, "VLLMClient", DummyVLLMClient)

    service_context.reset_service_context()

    context = service_context.get_service_context()

    _assert_faiss_manager(context.faiss_manager, expected_faiss_path)
    _assert_faiss_ready(context)

    with context.open_catalog() as catalog_obj:
        catalog = cast("RecordingDuckDBCatalog", catalog_obj)
        _assert_catalog(catalog, expected_duckdb_path, expected_vectors_dir)

    assertions.expect_true(catalog.closed, reason="catalog should be closed")

    service_context.reset_service_context()


def _assert_faiss_manager(manager: object, expected_path: Path) -> None:
    assertions.expect_true(
        isinstance(manager, RecordingFAISSManager), reason="manager should be RecordingFAISSManager"
    )
    if isinstance(manager, RecordingFAISSManager):
        assertions.expect_equal(manager.index_path, expected_path)


def _assert_faiss_ready(context: ApplicationContext) -> None:
    ready, limits, error = context.ensure_faiss_ready()
    assertions.expect_true(ready, reason="faiss should be ready")
    assertions.expect_equal(limits, [])
    assertions.expect_equal(error, None)
    manager = cast("RecordingFAISSManager", context.faiss_manager)
    assertions.expect_equal(manager.load_calls, 1)


def _assert_catalog(
    catalog: RecordingDuckDBCatalog, expected_db: Path, expected_vectors: Path
) -> None:
    assertions.expect_true(
        isinstance(catalog, RecordingDuckDBCatalog),
        reason="catalog should be RecordingDuckDBCatalog",
    )
    assertions.expect_equal(catalog.db_path, expected_db)
    assertions.expect_equal(catalog.vectors_dir, expected_vectors)
    assertions.expect_true(catalog.open_called, reason="catalog.open should have been called")
