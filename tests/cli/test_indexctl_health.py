"""Tests for `indexctl health` command."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from codeintel_rev.cli.indexctl import app as indexctl_app

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
    use_cuvs: bool = False
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


def test_health_command_reports_ok(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`indexctl health` reports OK when subsystems agree on counts."""
    vector_dim = constants.VECTOR_DIMS.small
    vector_count = constants.BATCH_SIZES.large
    manager = _ManagerStub(vec_dim=vector_dim, total=vector_count)
    catalog = _CatalogStub()
    monkeypatch.setattr("codeintel_rev.cli.indexctl._get_settings", lambda: _Settings(tmp_path))
    monkeypatch.setattr("codeintel_rev.cli.indexctl._faiss_manager", lambda *_: manager)
    monkeypatch.setattr("codeintel_rev.cli.indexctl._duckdb_catalog", lambda *_: catalog)
    monkeypatch.setattr("codeintel_rev.cli.indexctl._duckdb_embedding_dim", lambda _c: vector_dim)
    monkeypatch.setattr("codeintel_rev.cli.indexctl._count_idmap_rows", lambda _p: vector_count)
    result = cli.invoke(indexctl_app, ["health"], catch_exceptions=False)
    assertions.expect_equal(result.exit_code, 0, reason=result.output)
    payload = json.loads(result.stdout)
    assertions.expect_true(payload["ok"])
