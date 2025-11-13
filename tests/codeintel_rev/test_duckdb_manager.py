"""Unit tests for DuckDBManager."""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import cast

import duckdb
import pytest
from codeintel_rev.io.duckdb_manager import (
    DuckDBConfig,
    DuckDBManager,
    DuckDBQueryBuilder,
    DuckDBQueryOptions,
)


def test_duckdb_manager_configures_pragmas(tmp_path: Path) -> None:
    """Connections enable object cache and apply thread configuration."""
    manager = DuckDBManager(
        tmp_path / "catalog.duckdb", DuckDBConfig(threads=2, enable_object_cache=True)
    )

    with cast(
        "AbstractContextManager[duckdb.DuckDBPyConnection]",
        manager.connection(),
    ) as conn:
        threads_row = conn.execute("SELECT current_setting('threads')").fetchone()
        assert threads_row is not None
        assert int(threads_row[0]) == 2

        cache_row = conn.execute("SELECT current_setting('enable_object_cache')").fetchone()
        assert cache_row is not None
        assert str(cache_row[0]).lower() in {"true", "1"}


def test_duckdb_manager_closes_connections(tmp_path: Path) -> None:
    """Connections are closed after exiting the context manager."""
    manager = DuckDBManager(tmp_path / "catalog.duckdb")

    connection: duckdb.DuckDBPyConnection
    with cast(
        "AbstractContextManager[duckdb.DuckDBPyConnection]",
        manager.connection(),
    ) as connection:
        assert connection.execute("SELECT 1").fetchone() == (1,)

    with pytest.raises(duckdb.Error):
        connection.execute("SELECT 1")


def test_query_builder_basic() -> None:
    """Query builder constructs basic ID filter with parameter binding."""
    builder = DuckDBQueryBuilder()
    sql, params = builder.build_filter_query(chunk_ids=[1, 2, 3])

    assert "id = ANY($ids)" in sql
    assert params["ids"] == [1, 2, 3]
    assert "include" not in "".join(params.keys())


def test_query_builder_with_filters() -> None:
    """Query builder applies include/exclude globs and language filters."""
    builder = DuckDBQueryBuilder()
    options = DuckDBQueryOptions(
        include_globs=["src/**/*.py"],
        exclude_globs=["tests/**"],
        languages=["python", "typescript"],
    )
    sql, params = builder.build_filter_query(chunk_ids=[1], options=options)

    assert "c.uri LIKE $include_0" in sql
    assert params["include_0"] == "src/%/%.py"
    assert "c.uri NOT LIKE $exclude_0" in sql
    assert params["exclude_0"] == "tests/%"
    assert "c.lang = ANY($languages)" in sql
    assert params["languages"] == ["python", "typescript"]


def test_query_builder_preserve_order() -> None:
    """Query builder can preserve ID order with ordinality join."""
    builder = DuckDBQueryBuilder()
    options = DuckDBQueryOptions(
        include_globs=["src/**"],
        select_columns=("c.*",),
        preserve_order=True,
    )
    sql, params = builder.build_filter_query(chunk_ids=[3, 1], options=options)

    assert sql.startswith("SELECT c.*")
    assert "JOIN UNNEST($ids) WITH ORDINALITY" in sql
    assert "ORDER BY ids.position" in sql
    assert "c.uri LIKE $include_0" in sql
    assert params["ids"] == [3, 1]


def test_query_builder_join_flags() -> None:
    """Query builder adds optional joins when requested."""
    builder = DuckDBQueryBuilder()
    options = DuckDBQueryOptions(
        join_modules=True,
        join_symbols=True,
        join_faiss=True,
        join_ast=True,
        join_cst=True,
    )
    sql, _ = builder.build_filter_query(chunk_ids=[1], options=options)

    assert "LEFT JOIN modules USING" in sql
    assert "LEFT JOIN v_chunk_symbols" in sql
    assert "LEFT JOIN faiss_idmap" in sql
    assert "LEFT JOIN ast_nodes" in sql
    assert "LEFT JOIN cst_nodes" in sql


def test_connection_pool_reuses_connections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Connection pool limits concurrent connections and reuses them."""
    db_path = tmp_path / "pooled.duckdb"
    with duckdb.connect(str(db_path)) as conn:
        conn.execute("CREATE TABLE numbers(value INTEGER)")
        conn.execute("INSERT INTO numbers VALUES (1)")

    real_connect = duckdb.connect
    created: int = 0

    def _instrumented_connect(path: str) -> duckdb.DuckDBPyConnection:
        nonlocal created
        created += 1
        return real_connect(path)

    monkeypatch.setattr(
        "codeintel_rev.io.duckdb_manager.duckdb.connect",
        _instrumented_connect,
    )

    manager = DuckDBManager(db_path, DuckDBConfig(pool_size=2))

    for _ in range(10):
        with cast(
            "AbstractContextManager[duckdb.DuckDBPyConnection]",
            manager.connection(),
        ) as connection:
            assert connection.execute("SELECT value FROM numbers").fetchone() == (1,)

    manager.close()

    assert created <= 2
    assert manager.connections_created <= 2
