# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path

import pytest
from codeintel_rev.enrich.output_writers import write_jsonl, write_parquet_dataset


def test_jsonl_writer_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the orjson-backed JSONL writer emits stable bytes."""
    monkeypatch.setenv("ENRICH_JSONL_WRITER", "v2")
    path = tmp_path / "modules.jsonl"
    rows = [{"b": 2, "a": 1}, {"d": 4, "c": 3}]
    write_jsonl(path, rows)
    first = path.read_bytes()
    write_jsonl(path, rows)
    second = path.read_bytes()
    assert first == second
    assert first.endswith(b"\n")


def test_parquet_dataset_partitions_by_column(tmp_path: Path) -> None:
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
    assert table.num_rows == 2
    assert set(table.column("module_name").to_pylist()) == {"pkg.alpha", "pkg.beta"}
