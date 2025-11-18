"""ID-map export tests for FAISS store helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("faiss")
pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

from codeintel_rev.io.faiss_build import (  # noqa: E402
    IndexBuildConfig,
    add_vectors,
    build_primary_index,
)
from codeintel_rev.io.faiss_store import export_idmap_parquet  # noqa: E402

from tests._helpers import assertions  # noqa: E402


def test_export_idmap_parquet_schema_and_counts(tmp_path: Path) -> None:
    """ID-map Parquet export matches the FAISS ID count and schema."""
    d = 8
    n = 50
    rng = np.random.default_rng(4)
    vecs = rng.standard_normal((n, d), dtype=np.float32)
    ids = np.arange(10_000, 10_000 + n, dtype=np.int64)

    cfg = IndexBuildConfig(vec_dim=d, default_nlist=64)
    index, _factory = build_primary_index(vecs, cfg=cfg, override_family="flat")
    add_vectors(index, vecs, ids)

    out_path = tmp_path / "idmap.parquet"
    rows = export_idmap_parquet(index, out_path)
    assertions.expect_equal(rows, n, reason="Row count must match vector count")

    table = pq.read_table(out_path)
    assertions.expect_equal(table.num_rows, n)
    assertions.expect_true(
        {"faiss_row", "external_id"}.issubset(set(table.column_names)),
        reason="Sidecar schema missing expected columns",
    )
