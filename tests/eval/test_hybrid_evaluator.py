"""Tests for evaluation helpers."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from codeintel_rev.eval.pool_writer import write_pool
from codeintel_rev.retrieval.types import SearchPoolRow

from tests._helpers import assertions


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
    assertions.expect_equal(total, 3)
    table = pq.read_table(out)
    assertions.expect_equal(
        set(table.column_names), {"query_id", "channel", "rank", "chunk_id", "score", "reason"}
    )
    assertions.expect_equal(table.num_rows, 3)
    reason_payloads = table.column("reason").to_pylist()
    first_reason = reason_payloads[0]
    second_reason = reason_payloads[1]
    assertions.expect_true(
        isinstance(first_reason, Mapping), reason="first_reason should be Mapping"
    )
    assertions.expect_true(
        isinstance(second_reason, Mapping), reason="second_reason should be Mapping"
    )
    if not isinstance(first_reason, Mapping) or not isinstance(second_reason, Mapping):
        pytest.fail("reasons should be mappings")
    assertions.expect_sequence_equal(first_reason["matched_symbols"], ["foo"])
    assertions.expect_sequence_equal(second_reason["matched_symbols"], [])
