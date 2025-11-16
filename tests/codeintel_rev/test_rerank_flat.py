from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.retrieval.rerank_flat import FlatReranker, exact_rerank

from tests._helpers import assertions


def test_exact_rerank_prefers_vectors_with_higher_similarity(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.duckdb"
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()
    catalog = DuckDBCatalog(catalog_path, vectors_dir)
    with duckdb.connect(str(catalog_path)) as connection:
        connection.execute(
            """
            CREATE OR REPLACE VIEW chunks AS
            SELECT * FROM (
                SELECT 1::BIGINT AS id, [1.0, 0.0]::FLOAT[] AS embedding
                UNION ALL
                SELECT 2::BIGINT AS id, [0.0, 1.0]::FLOAT[] AS embedding
            )
            """
        )

    queries = np.array([[0.9, 0.1]], dtype=np.float32)
    candidates = np.array([[1, 2]], dtype=np.int64)

    scores, ids = exact_rerank(catalog, queries, candidates, top_k=2)

    assertions.expect_equal(ids.shape, (1, 2))
    assertions.expect_equal(scores.shape, (1, 2))
    # Chunk 1 aligns best with the query vector.
    assertions.expect_equal(ids.tolist()[0][0], 1)
    assertions.expect_equal(ids.tolist()[0][1], 2)


def test_flat_reranker_supports_cosine_metric(tmp_path: Path) -> None:
    catalog_path = tmp_path / "catalog.duckdb"
    vectors_dir = tmp_path / "vectors"
    vectors_dir.mkdir()
    catalog = DuckDBCatalog(catalog_path, vectors_dir)
    with duckdb.connect(str(catalog_path)) as connection:
        connection.execute(
            """
            CREATE OR REPLACE VIEW chunks AS
            SELECT * FROM (
                SELECT 10::BIGINT AS id, [1.0, 0.0]::FLOAT[] AS embedding
                UNION ALL
                SELECT 20::BIGINT AS id, [0.0, 1.0]::FLOAT[] AS embedding
            )
            """
        )

    reranker = FlatReranker(catalog, metric="cos")
    queries = np.array([[0.0, 1.0]], dtype=np.float32)
    candidates = np.array([[10, 20]], dtype=np.int64)

    scores, ids = reranker.rerank(queries, candidates, top_k=1)

    assertions.expect_sequence_equal(ids.tolist(), [[20]])
    # Cosine similarity of perfectly aligned vectors equals 1.0.
    assertions.expect_true(np.isclose(scores[0][0], 1.0), reason="cosine similarity should be 1.0")
