"""Tests for `indexctl health` command."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from codeintel_rev.cli.indexctl import IndexctlCliContext
from codeintel_rev.cli.indexctl import app as indexctl_app
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.io.faiss_manager import FAISSManager

from tests._helpers import assertions, cli, constants


class _ManagerStub:
    """FAISS manager stub exposing the minimal API under test."""

    def __init__(self, vec_dim: int, total: int) -> None:
        self.vec_dim = vec_dim
        self._cpu_index = SimpleNamespace(ntotal=total)

    def require_cpu_index(self) -> SimpleNamespace:
        return self._cpu_index


class _ConnectionStub:
    def execute(self, *_args: object, **_kwargs: object) -> _ConnectionStub:
        return self

    @staticmethod
    def fetchone() -> tuple[int]:
        return (1,)


class _ConnectionCtx:
    def __enter__(self) -> _ConnectionStub:
        return _ConnectionStub()

    def __exit__(self, *_args: object) -> None:
        return None


class _CatalogStub:
    """DuckDB catalog stub used to track view creation calls."""

    def __init__(self) -> None:
        self.view_calls = 0

    def ensure_faiss_idmap_views(self, *_args: object) -> None:
        self.view_calls += 1

    @staticmethod
    def connection() -> _ConnectionCtx:
        return _ConnectionCtx()

    @staticmethod
    def count_chunks() -> int:
        return constants.BATCH_SIZES.large

    @staticmethod
    def close() -> None:  # pragma: no cover - no-op
        return None


class _Paths(SimpleNamespace):
    faiss_index: str
    duckdb_path: str
    faiss_idmap_path: str
    vectors_dir: str
    repo_root: str


class _IndexCfg(SimpleNamespace):
    nlist: int = 1
    vec_dim: int = constants.VECTOR_DIMS.small
    duckdb_materialize: bool = False


class _Settings(SimpleNamespace):
    def __init__(self, base: Path) -> None:
        paths = _Paths(
            faiss_index=str(base / "faiss.index"),
            duckdb_path=str(base / "catalog.duckdb"),
            faiss_idmap_path=str(base / "faiss_idmap.parquet"),
            vectors_dir=str(base),
            repo_root=str(base),
        )
        super().__init__(paths=paths, index=_IndexCfg())


def test_health_command_reports_ok(tmp_path: Path) -> None:
    """`indexctl health` reports OK when subsystems agree on counts."""
    vector_dim = constants.VECTOR_DIMS.small
    vector_count = constants.BATCH_SIZES.large
    manager = _ManagerStub(vec_dim=vector_dim, total=vector_count)
    catalog = _CatalogStub()
    base_context = IndexctlCliContext.production()
    context = replace(
        base_context,
        settings_factory=lambda: cast("Any", _Settings(tmp_path)),
        faiss_manager_factory=lambda *_: cast("FAISSManager", manager),
        duckdb_catalog_factory=lambda *_: cast("DuckDBCatalog", catalog),
        duckdb_dim_resolver=lambda _catalog: vector_dim,
        idmap_row_counter=lambda _path: vector_count,
    )
    result = cli.invoke(
        indexctl_app,
        ["health"],
        catch_exceptions=False,
        obj={"cli_context": context},
    )
    assertions.expect_equal(result.exit_code, 0, reason=result.output)
    payload = json.loads(result.stdout)
    assertions.expect_true(payload["ok"])
