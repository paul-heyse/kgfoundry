# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path

import pytest
from codeintel_rev.enrich.duckdb_store import DuckConn, ingest_modules_jsonl


@pytest.mark.duckdb
def test_ingest_modules_jsonl_native_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    duckdb = pytest.importorskip("duckdb")
    db_path = tmp_path / "catalog.duckdb"
    modules_jsonl = tmp_path / "modules.jsonl"
    modules_jsonl.write_text('{"path":"a.py","docstring":"one"}\n', encoding="utf-8")
    monkeypatch.setattr("codeintel_rev.enrich.duckdb_store._USE_NATIVE_JSON", True, raising=False)
    count = ingest_modules_jsonl(DuckConn(db_path=db_path), modules_jsonl)
    assert count == 1

    modules_jsonl.write_text(
        '{"path":"a.py","docstring":"updated"}\n{"path":"b.py","docstring":"two"}\n',
        encoding="utf-8",
    )
    count = ingest_modules_jsonl(DuckConn(db_path=db_path), modules_jsonl)
    assert count == 2
    with duckdb.connect(str(db_path)) as con:
        rows = con.execute("SELECT path, docstring FROM modules ORDER BY path").fetchall()
    assert rows == [("a.py", "updated"), ("b.py", "two")]
