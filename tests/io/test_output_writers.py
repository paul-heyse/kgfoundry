# SPDX-License-Identifier: MIT
"""Tests for output writers: JSONL and Parquet dataset writing."""

from __future__ import annotations

from pathlib import Path

import pytest
from codeintel_rev.enrich.output_writers import (
    override_writer_env,
    write_jsonl,
    write_parquet_dataset,
)

from tests._helpers import assertions


def test_jsonl_writer_is_deterministic(tmp_path: Path) -> None:
    """Ensure the orjson-backed JSONL writer emits stable bytes."""
    path = tmp_path / "modules.jsonl"
    rows = [{"b": 2, "a": 1}, {"d": 4, "c": 3}]
    with override_writer_env(lambda key, default=None: "v2" if key == "ENRICH_JSONL_WRITER" else default):
        write_jsonl(path, rows, writer_version="v2")
        first = path.read_bytes()
        write_jsonl(path, rows, writer_version="v2")
        second = path.read_bytes()
    assertions.expect_equal(first, second)
    assertions.expect_true(first.endswith(b"\n"), reason="jsonl should end with newline")


def test_parquet_dataset_partitions_by_column(tmp_path: Path) -> None:
    """Test that parquet dataset writer partitions data by specified column."""
    ds = pytest.importorskip("pyarrow.dataset")
    rows = [
        {"module_name": "pkg.alpha", "path": "pkg/alpha.py", "language": "py"},
        {"module_name": "pkg.beta", "path": "pkg/beta.py", "language": "py"},
    ]
    out_dir = tmp_path / "dataset"
    write_parquet_dataset(
        out_dir,
        rows,
        partitioning=["module_name"],
        dictionary_fields=("module_name", "path"),
    )
    dataset = ds.dataset(out_dir, format="parquet", partitioning="hive")
    table = dataset.to_table()
    assertions.expect_equal(table.num_rows, 2)
    assertions.expect_equal(set(table.column("module_name").to_pylist()), {"pkg.alpha", "pkg.beta"})
