"""Tests for evaluation helpers."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
from codeintel_rev.eval.pool_writer import PoolRow, write_pool


def test_pool_writer_sources(tmp_path: Path) -> None:
    """Pool writer records sources and scores in Parquet format."""
    rows = [
        PoolRow("q1", "faiss", 1, 101, 0.9, "repo://chunks/101"),
        PoolRow("q1", "bm25", 1, 202, 12.0, "repo://chunks/202"),
        PoolRow("q2", "oracle", 1, 303, 0.95, "repo://chunks/303"),
    ]
    out = tmp_path / "pool.parquet"
    total = write_pool(rows, out)
    assert total == 3
    table = pq.read_table(out)
    assert set(table.column_names) == {"query_id", "source", "rank", "chunk_id", "score"}
    assert table.num_rows == 3
