"""Tests for `indexctl health` command."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from codeintel_rev.cli.indexctl import IndexctlCliContext
from codeintel_rev.cli.indexctl import app as indexctl_app
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.io.faiss_manager import FAISSManager

from tests._helpers import assertions, cli, constants
from tests._helpers.settings import build_app_config_for_repo


class _ManagerStub:
    """FAISS manager stub exposing the minimal API under test."""

    def __init__(self, vec_dim: int, total: int) -> None:
        self.vec_dim = vec_dim
        self._cpu_index = SimpleNamespace(ntotal=total)

    def require_cpu_index(self) -> SimpleNamespace:
        """Return CPU index stub.

        Returns
        -------
        SimpleNamespace
            Fake CPU index with ntotal attribute.
        """
        return self._cpu_index


class _ConnectionStub:
    def execute(self, *_args: object, **_kwargs: object) -> _ConnectionStub:
        """Execute SQL query and return self for chaining.

        Parameters
        ----------
        *_args : object
            Positional arguments (unused).
        **_kwargs : object
            Keyword arguments (unused).

        Returns
        -------
        _ConnectionStub
            Self for method chaining.
        """
        return self

    @staticmethod
    def fetchone() -> tuple[int]:
        """Return fake query result.

        Returns
        -------
        tuple[int]
            Tuple containing single integer value 1.
        """
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
        """Increment view creation call counter.

        Parameters
        ----------
        *_args : object
            Positional arguments (unused).
        """
        self.view_calls += 1

    @staticmethod
    def connection() -> _ConnectionCtx:
        """Return connection context manager stub.

        Returns
        -------
        _ConnectionCtx
            Fake connection context manager.
        """
        return _ConnectionCtx()

    @staticmethod
    def count_chunks() -> int:
        """Return fake chunk count.

        Returns
        -------
        int
            Large batch size constant.
        """
        return constants.BATCH_SIZES.large

    @staticmethod
    def close() -> None:  # pragma: no cover - no-op
        """Close catalog stub (no-op)."""
        return


def test_health_command_reports_ok(tmp_path: Path) -> None:
    """`indexctl health` reports OK when subsystems agree on counts."""
    vector_dim = constants.VECTOR_DIMS.small
    vector_count = constants.BATCH_SIZES.large
    manager = _ManagerStub(vec_dim=vector_dim, total=vector_count)
    catalog = _CatalogStub()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    app_config = build_app_config_for_repo(repo_root)
    base_context = IndexctlCliContext.production()
    context = replace(
        base_context,
        app_config_factory=lambda: app_config,
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
