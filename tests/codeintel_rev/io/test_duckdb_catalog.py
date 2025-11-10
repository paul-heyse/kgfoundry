"""Tests for DuckDB catalog helpers."""

from __future__ import annotations

import duckdb
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog


def test_relation_exists_detects_tables() -> None:
    """Tables reported by information_schema are considered relations."""
    conn = duckdb.connect(":memory:")
    try:
        conn.execute("CREATE TABLE foo(id INTEGER)")
        assert DuckDBCatalog.relation_exists(conn, "foo")
    finally:
        conn.close()


def test_relation_exists_detects_views() -> None:
    """Views are also treated as relations and return True."""
    conn = duckdb.connect(":memory:")
    try:
        conn.execute("CREATE TABLE foo(id INTEGER)")
        conn.execute("CREATE VIEW foo_view AS SELECT * FROM foo")
        assert DuckDBCatalog.relation_exists(conn, "foo_view")
    finally:
        conn.close()


def test_relation_exists_returns_false_for_missing_relation() -> None:
    """Missing relations return False."""
    conn = duckdb.connect(":memory:")
    try:
        assert not DuckDBCatalog.relation_exists(conn, "does_not_exist")
    finally:
        conn.close()
