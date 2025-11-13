"""Tests for evaluation helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
from codeintel_rev.eval.pool_writer import write_pool
from codeintel_rev.retrieval.types import SearchPoolRow


def test_pool_writer_sources(tmp_path: Path) -> None:
    """Pool writer records sources and scores in Parquet format."""
    rows = [
        SearchPoolRow("q1", "faiss", 1, 101, 0.9, {"uri": "repo://chunks/101"}),
        SearchPoolRow("q1", "bm25", 1, 202, 12.0, {"uri": "repo://chunks/202"}),
        SearchPoolRow("q2", "oracle", 1, 303, 0.95, {"uri": "repo://chunks/303"}),
    ]
    out = tmp_path / "pool.parquet"
    total = write_pool(rows, out)
    assert total == 3
    table = pq.read_table(out)
    assert set(table.column_names) == {"query_id", "channel", "rank", "id", "score", "meta"}
    assert table.num_rows == 3
    meta_payloads: list[dict[str, object]] = []
    for text in table.column("meta").to_pylist():
        assert text is not None
        meta_payloads.append(json.loads(text))
    assert meta_payloads[0]["uri"] == "repo://chunks/101"
