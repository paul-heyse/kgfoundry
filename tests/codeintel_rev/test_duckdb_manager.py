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

from tests._helpers import assertions, constants


def test_duckdb_manager_configures_pragmas(tmp_path: Path) -> None:
    """Connections enable object cache and apply thread configuration."""
    thread_count = constants.BATCH_SIZES.small
    manager = DuckDBManager(
        tmp_path / "catalog.duckdb",
        DuckDBConfig(threads=thread_count, enable_object_cache=True),
    )

    with cast(
        "AbstractContextManager[duckdb.DuckDBPyConnection]",
        manager.connection(),
    ) as conn:
        threads_row = conn.execute("SELECT current_setting('threads')").fetchone()
        assertions.expect_true(threads_row is not None)
        assertions.expect_equal(int(threads_row[0]), thread_count)

        cache_row = conn.execute("SELECT current_setting('enable_object_cache')").fetchone()
        assertions.expect_true(cache_row is not None)
        assertions.expect_true(str(cache_row[0]).lower() in {"true", "1"})


def test_duckdb_manager_closes_connections(tmp_path: Path) -> None:
    """Connections are closed after exiting the context manager."""
    manager = DuckDBManager(tmp_path / "catalog.duckdb")

    connection: duckdb.DuckDBPyConnection
    with cast(
        "AbstractContextManager[duckdb.DuckDBPyConnection]",
        manager.connection(),
    ) as connection:
        assertions.expect_equal(connection.execute("SELECT 1").fetchone(), (1,))

    with pytest.raises(duckdb.Error):
        connection.execute("SELECT 1")


def test_query_builder_basic() -> None:
    """Query builder constructs basic ID filter with parameter binding."""
    builder = DuckDBQueryBuilder()
    sql, params = builder.build_filter_query(chunk_ids=[1, 2, 3])

    assertions.expect_in("id = ANY($ids)", sql)
    assertions.expect_sequence_equal(params["ids"], [1, 2, 3])
    assertions.expect_true("include" not in "".join(params.keys()))


def test_query_builder_with_filters() -> None:
    """Query builder applies include/exclude globs and language filters."""
    builder = DuckDBQueryBuilder()
    options = DuckDBQueryOptions(
        include_globs=["src/**/*.py"],
        exclude_globs=["tests/**"],
        languages=["python", "typescript"],
    )
    sql, params = builder.build_filter_query(chunk_ids=[1], options=options)

    assertions.expect_in("c.uri LIKE $include_0", sql)
    assertions.expect_equal(params["include_0"], "src/%/%.py")
    assertions.expect_in("c.uri NOT LIKE $exclude_0", sql)
    assertions.expect_equal(params["exclude_0"], "tests/%")
    assertions.expect_in("c.lang = ANY($languages)", sql)
    assertions.expect_sequence_equal(params["languages"], ["python", "typescript"])


def test_query_builder_preserve_order() -> None:
    """Query builder can preserve ID order with ordinality join."""
    builder = DuckDBQueryBuilder()
    options = DuckDBQueryOptions(
        include_globs=["src/**"],
        select_columns=("c.*",),
        preserve_order=True,
    )
    sql, params = builder.build_filter_query(chunk_ids=[3, 1], options=options)

    assertions.expect_true(sql.startswith("SELECT c.*"))
    assertions.expect_in("JOIN UNNEST($ids) WITH ORDINALITY", sql)
    assertions.expect_in("ORDER BY ids.position", sql)
    assertions.expect_in("c.uri LIKE $include_0", sql)
    assertions.expect_sequence_equal(params["ids"], [3, 1])


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

    assertions.expect_in("LEFT JOIN modules USING", sql)
    assertions.expect_in("LEFT JOIN v_chunk_symbols", sql)
    assertions.expect_in("LEFT JOIN faiss_idmap", sql)
    assertions.expect_in("LEFT JOIN ast_nodes", sql)
    assertions.expect_in("LEFT JOIN cst_nodes", sql)


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
            assertions.expect_equal(
                connection.execute("SELECT value FROM numbers").fetchone(), (1,)
            )

    manager.close()

    assertions.expect_true(created <= manager.config.pool_size)
    assertions.expect_true(manager.connections_created <= manager.config.pool_size)
