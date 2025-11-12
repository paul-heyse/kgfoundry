"""Tests for FAISSManager IDMap export helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from codeintel_rev.io.faiss_manager import FAISSManager


def test_export_idmap_round_trip(tmp_path: Path) -> None:
    """Exported ID map reflects the chunk IDs added to the index."""
    vec_dim = 16
    vectors = np.random.RandomState(0).randn(32, vec_dim).astype(np.float32)
    ids = np.arange(32, dtype=np.int64)

    manager = FAISSManager(index_path=tmp_path / "index.faiss", vec_dim=vec_dim, use_cuvs=False)
    manager.build_index(vectors)
    manager.add_vectors(vectors, ids)
    manager.save_cpu_index()

    # Reload to ensure persistence path exercises load code paths.
    manager.load_cpu_index()
    out_path = tmp_path / "faiss_idmap.parquet"
    rows = manager.export_idmap(out_path)
    assert rows == 32

    table = pq.read_table(out_path)
    assert set(table.column_names) == {"faiss_row", "external_id"}
    assert table.num_rows == 32
    assert table.column("external_id").to_pylist()[:5] == [0, 1, 2, 3, 4]
