"""Tests for evaluation helpers."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pyarrow.parquet as pq
from codeintel_rev.eval.pool_writer import write_pool
from codeintel_rev.retrieval.types import SearchPoolRow


def test_pool_writer_sources(tmp_path: Path) -> None:
    """Pool writer records sources and scores in Parquet format."""
    rows = [
        SearchPoolRow(
            "q1",
            "faiss",
            1,
            101,
            0.9,
            {"matched_symbols": ["foo"], "ast_kind": "FunctionDef", "cst_hits": ["call"]},
        ),
        SearchPoolRow("q1", "bm25", 1, 202, 12.0, {"matched_symbols": []}),
        SearchPoolRow("q2", "oracle", 1, 303, 0.95, {}),
    ]
    out = tmp_path / "pool.parquet"
    total = write_pool(rows, out)
    assert total == 3
    table = pq.read_table(out)
    assert set(table.column_names) == {"query_id", "channel", "rank", "chunk_id", "score", "reason"}
    assert table.num_rows == 3
    reason_payloads = table.column("reason").to_pylist()
    first_reason = reason_payloads[0]
    second_reason = reason_payloads[1]
    assert isinstance(first_reason, Mapping)
    assert isinstance(second_reason, Mapping)
    assert first_reason["matched_symbols"] == ["foo"]
    assert second_reason["matched_symbols"] == []
