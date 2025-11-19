"""Tests covering the shared Parquet/JSONL writer helper."""

from __future__ import annotations

from pathlib import Path

import pytest
from codeintel_rev.enrich.output_writers import write_parquet_or_jsonl

from tests._helpers import assertions


def test_write_parquet_or_jsonl_uses_fallback_for_empty(tmp_path: Path) -> None:
    """Ensure the helper produces a JSONL fallback when no rows are present."""
    parquet = tmp_path / "edges.parquet"
    jsonl = tmp_path / "edges.jsonl"
    used, count = write_parquet_or_jsonl(parquet, jsonl, [])
    assertions.expect_equal(used, jsonl)
    assertions.expect_equal(count, 0)
    assertions.expect_true(used.exists())


def test_write_parquet_or_jsonl_prefers_parquet_when_available(tmp_path: Path) -> None:
    """Verify Parquet output is used when PyArrow is installed."""
    pytest.importorskip("pyarrow.parquet")
    parquet = tmp_path / "edges.parquet"
    jsonl = tmp_path / "edges.jsonl"
    used, count = write_parquet_or_jsonl(parquet, jsonl, [{"src": "a", "dst": "b"}])
    assertions.expect_equal(used.suffix, ".parquet")
    assertions.expect_equal(count, 1)
    assertions.expect_true(used.exists())
