# SPDX-License-Identifier: MIT
"""Tests for DuckDB module ingestion from JSONL files."""

from __future__ import annotations

from pathlib import Path

import pytest
from codeintel_rev.enrich.duckdb_store import DuckConn, DuckDBIngestContext, ingest_modules_jsonl

from tests._helpers import assertions


@pytest.mark.duckdb
def test_ingest_modules_jsonl_native_path(tmp_path: Path) -> None:
    """Test that ingest_modules_jsonl uses native JSON path for DuckDB operations."""
    duckdb = pytest.importorskip("duckdb")
    db_path = tmp_path / "catalog.duckdb"
    modules_jsonl = tmp_path / "modules.jsonl"
    modules_jsonl.write_text('{"path":"a.py","docstring":"one"}\n', encoding="utf-8")
    context = DuckDBIngestContext(duckdb_module=duckdb, use_native_json=True, pragmas=())
    count = ingest_modules_jsonl(DuckConn(db_path=db_path), modules_jsonl, context=context)
    assertions.expect_equal(count, 1)

    modules_jsonl.write_text(
        '{"path":"a.py","docstring":"updated"}\n{"path":"b.py","docstring":"two"}\n',
        encoding="utf-8",
    )
    count = ingest_modules_jsonl(DuckConn(db_path=db_path), modules_jsonl, context=context)
    assertions.expect_equal(count, 2)
    with duckdb.connect(str(db_path)) as con:
        rows = con.execute("SELECT path, docstring FROM modules ORDER BY path").fetchall()
    assertions.expect_sequence_equal(rows, [("a.py", "updated"), ("b.py", "two")])
