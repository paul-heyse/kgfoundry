"""FAISS dual-search helper tests covering merge and refine paths."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import numpy as np
import pytest

pytest.importorskip("faiss")

from codeintel_rev.io import faiss_runtime as runtime_module
from codeintel_rev.io.faiss_build import (
    IndexBuildConfig,
    add_vectors,
    build_primary_index,
    create_secondary_index,
)
from codeintel_rev.io.faiss_runtime import search_dual

from tests._helpers import assertions

if TYPE_CHECKING:  # pragma: no cover - typing-only dependency
    from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
else:  # pragma: no cover - runtime import avoided
    DuckDBCatalog = Any

_MERGE_K = 20
_REFINE_K = 10


def _mk_index(n: int, d: int, seed: int) -> tuple[Any, np.ndarray, np.ndarray]:
    """Construct a trained flat FAISS index for test scenarios.

    Parameters
    ----------
    n : int
        Number of vectors to populate inside the index.
    d : int
        Embedding dimensionality.
    seed : int
        Seed applied to the random generator for deterministic vectors.

    Returns
    -------
    tuple[Any, np.ndarray, np.ndarray]
        Populated index, normalized vectors, and ID array used for additions.
    """
    rng = np.random.default_rng(seed)
    vecs = rng.standard_normal((n, d), dtype=np.float32)
    ids = np.arange(n, dtype=np.int64)
    cfg = IndexBuildConfig(vec_dim=d, default_nlist=256)
    index, _factory = build_primary_index(vecs, cfg=cfg, override_family="flat")
    add_vectors(index, vecs, ids)
    return index, vecs, ids


def test_dual_search_merge_no_refine() -> None:
    """Ensure merged searches deduplicate IDs without refine pipeline."""
    d = 16
    primary, pvecs, _ = _mk_index(200, d, seed=1)

    secondary = create_secondary_index(d)
    s_rng = np.random.default_rng(2)
    svecs = s_rng.standard_normal((30, d), dtype=np.float32)
    sids = np.arange(10_000, 10_000 + 30, dtype=np.int64)
    add_vectors(secondary, svecs, sids)

    query = pvecs[0].astype(np.float32)
    distances, ids = search_dual(
        primary=primary,
        secondary=secondary,
        query=query,
        k=_MERGE_K,
        nprobe=None,
        refine_k_factor=1.0,
        catalog=None,
    )
    assertions.expect_equal(distances.shape, (1, _MERGE_K))
    assertions.expect_equal(ids.shape, (1, _MERGE_K))
    unique = len(set(ids[0].tolist()))
    assertions.expect_equal(unique, _MERGE_K, reason="Merged results must dedupe IDs")


def test_dual_search_merge_with_refine() -> None:
    """Trigger refine path to ensure reranker output shapes are respected."""

    def fake_exact_rerank(
        _catalog: object,
        _query: np.ndarray,
        candidate_ids: np.ndarray,
        *,
        top_k: int,
        metric: str,
    ) -> tuple[np.ndarray, np.ndarray]:
        del metric
        batch = candidate_ids.shape[0]
        distances = np.full((batch, top_k), 1.0, dtype=np.float32)
        ids = candidate_ids[:, :top_k].astype(np.int64, copy=False)
        return distances, ids

    d = 16
    primary, pvecs, _ = _mk_index(120, d, seed=3)
    query = pvecs[1].astype(np.float32)

    class FakeCatalog:
        """Catalog stub used to trigger refine path."""

    catalog = cast("DuckDBCatalog", FakeCatalog())
    with runtime_module.override_exact_rerank(fake_exact_rerank):
        distances, ids = search_dual(
            primary=primary,
            secondary=None,
            query=query,
            k=_REFINE_K,
            nprobe=None,
            refine_k_factor=2.0,
            catalog=catalog,
        )
    assertions.expect_equal(distances.shape, (1, _REFINE_K))
    assertions.expect_equal(ids.shape, (1, _REFINE_K))
