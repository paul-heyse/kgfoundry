"""Integration tests for FAISS builder family selection and persistence."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("faiss")

from codeintel_rev.io.faiss_build import (
    IndexBuildConfig,
    add_vectors,
    build_primary_index,
    choose_family,
    load_index,
    save_index,
)

from tests._helpers import assertions


@pytest.mark.parametrize(
    ("n", "expected"),
    [(100, "flat"), (6_000, "ivfflat"), (100_000, "ivfpq")],
)
def test_choose_family_thresholds(n: int, expected: str) -> None:
    """Verify adaptive family selection thresholds."""
    cfg = IndexBuildConfig(vec_dim=32, default_nlist=1_024)
    assertions.expect_equal(choose_family(n, cfg), expected)


def test_roundtrip_save_load(tmp_path: Path) -> None:
    """Persist and reload an IVFFlat index without data loss."""
    d = 32
    n = 1_000
    cfg = IndexBuildConfig(vec_dim=d, default_nlist=512)
    rng = np.random.default_rng(0)
    vecs = rng.standard_normal((n, d), dtype=np.float32)
    ids = np.arange(n, dtype=np.int64)

    index, _factory = build_primary_index(vecs, cfg=cfg, override_family="ivfflat")
    add_vectors(index, vecs, ids)

    path = tmp_path / "primary.faiss"
    save_index(index, path)

    loaded = load_index(path)
    assertions.expect_equal(int(loaded.d), d, reason="Dimension mismatch")
    assertions.expect_equal(
        int(loaded.ntotal),
        n,
        reason="Vector count mismatch after load",
    )
