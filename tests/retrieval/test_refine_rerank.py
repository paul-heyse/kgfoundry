"""Tests for FAISSManager.search_with_refine."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import numpy as np
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.io.faiss_manager import FAISSManager

from tests._helpers import assertions


class _CatalogStub:
    """Minimal DuckDB catalog stub returning deterministic embeddings."""

    def __init__(self, embeddings: dict[int, np.ndarray]) -> None:
        self._embeddings = embeddings

    def get_embeddings_by_ids(self, ids: list[int]) -> tuple[list[int], np.ndarray]:
        filtered = [chunk_id for chunk_id in ids if chunk_id in self._embeddings]
        if not filtered:
            dim = len(next(iter(self._embeddings.values())))
            return [], np.empty((0, dim), dtype=np.float32)
        stacked = np.vstack([self._embeddings[chunk_id] for chunk_id in filtered]).astype(
            np.float32
        )
        return filtered, stacked


def test_search_with_refine_returns_ordered_hits(tmp_path: Path) -> None:
    vec_dim = 4
    base_vectors = np.eye(vec_dim, dtype=np.float32)
    manager = FAISSManager(index_path=tmp_path / "index.faiss", vec_dim=vec_dim)
    manager.build_index(base_vectors)
    manager.add_vectors(base_vectors, np.arange(vec_dim, dtype=np.int64))
    manager.save_cpu_index()
    manager.load_cpu_index()
    catalog = _CatalogStub({int(idx): base_vectors[idx] for idx in range(vec_dim)})
    query = base_vectors[0].reshape(1, -1)
    hits = manager.search_with_refine(query, k=2, catalog=cast("DuckDBCatalog", catalog))
    assertions.expect_true(bool(hits), reason="search_with_refine should return at least one hit")
    assertions.expect_equal(int(hits[0].doc_id), 0)
    assertions.expect_equal(hits[0].rank, 0)
    k_factor = hits[0].explain.get("k_factor")
    assertions.expect_true(isinstance(k_factor, float), reason="k_factor should be float")
    assertions.expect_true(k_factor >= 1.0, reason="k_factor should be at least 1.0")
