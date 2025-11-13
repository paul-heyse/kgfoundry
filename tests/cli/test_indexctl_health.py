"""Tests for `indexctl health` command."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from tests.cli.test_indexctl_embeddings import _load_cli_app

indexctl_app = _load_cli_app()


class _ManagerStub:
    def __init__(self, vec_dim: int, total: int) -> None:
        self.vec_dim = vec_dim
        self._cpu_index = SimpleNamespace(ntotal=total)

    def require_cpu_index(self) -> Any:
        return self._cpu_index


class _ConnectionStub:
    def execute(self, *_args: object, **_kwargs: object) -> _ConnectionStub:
        return self

    def fetchone(self) -> tuple[int]:
        return (1,)


class _ConnectionCtx:
    def __enter__(self) -> _ConnectionStub:
        return _ConnectionStub()

    def __exit__(self, *_args: object) -> None:
        return None


class _CatalogStub:
    def __init__(self) -> None:
        self.view_calls = 0

    def ensure_faiss_idmap_views(self, *_args: object) -> None:
        self.view_calls += 1

    def connection(self) -> _ConnectionCtx:
        return _ConnectionCtx()

    def count_chunks(self) -> int:
        return 5

    def close(self) -> None:  # pragma: no cover - no-op
        return None


class _Paths(SimpleNamespace):
    faiss_index: str
    duckdb_path: str
    faiss_idmap_path: str
    vectors_dir: str
    repo_root: str


class _IndexCfg(SimpleNamespace):
    nlist: int = 1
    vec_dim: int = 4
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
    manager = _ManagerStub(vec_dim=4, total=4)
    catalog = _CatalogStub()
    monkeypatch.setattr("codeintel_rev.cli.indexctl._get_settings", lambda: _Settings(tmp_path))
    monkeypatch.setattr("codeintel_rev.cli.indexctl._faiss_manager", lambda *_: manager)
    monkeypatch.setattr("codeintel_rev.cli.indexctl._duckdb_catalog", lambda *_: catalog)
    monkeypatch.setattr("codeintel_rev.cli.indexctl._duckdb_embedding_dim", lambda _c: 4)
    monkeypatch.setattr("codeintel_rev.cli.indexctl._count_idmap_rows", lambda _p: 4)
    runner = CliRunner()
    result = runner.invoke(indexctl_app, ["health"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
