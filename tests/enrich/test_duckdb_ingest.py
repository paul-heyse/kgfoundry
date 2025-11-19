# SPDX-License-Identifier: MIT
"""Tests for DuckDB module ingestion from JSONL files."""

from __future__ import annotations

import json
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


@pytest.mark.duckdb
def test_ingest_modules_jsonl_persists_meta(tmp_path: Path) -> None:
    """DuckDB ingestion should store meta JSON and hydrate legacy imports."""
    duckdb = pytest.importorskip("duckdb")
    db_path = tmp_path / "catalog.duckdb"
    modules_jsonl = tmp_path / "modules.jsonl"
    payload = {
        "path": "pkg/app.py",
        "docstring": "Doc",
        "meta": {
            "imports": [
                {"src_module": "pkg.app", "dst_module": "pkg.utils", "alias": None, "level": 0}
            ],
            "definitions": [
                {"module": "pkg.app", "name": "run", "kind": "function", "lineno": 10},
            ],
            "exports": [
                {"module": "pkg.app", "name": "Foo", "kind": "class", "via_dunder_all": True},
            ],
            "legacy_imports": [
                {
                    "module": "pkg.utils",
                    "names": ["helper"],
                    "aliases": {},
                    "is_star": False,
                    "level": 0,
                }
            ],
        },
    }
    modules_jsonl.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    context = DuckDBIngestContext(duckdb_module=duckdb, use_native_json=False, pragmas=())
    count = ingest_modules_jsonl(DuckConn(db_path=db_path), modules_jsonl, context=context)
    assertions.expect_equal(count, 1)
    with duckdb.connect(str(db_path)) as con:
        row = con.execute("SELECT meta, imports FROM modules WHERE path='pkg/app.py'").fetchone()
    assertions.expect_true(isinstance(row, tuple), reason="Expected query row")
    meta = json.loads(row[0])
    assertions.expect_equal(meta["exports"][0]["name"], "Foo")
    assertions.expect_true(row[1] is None)
