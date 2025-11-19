"""Smoke tests for sparse retrieval fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from codeintel_rev.io.bm25_manager import BM25QueryEngine, BM25QueryOptions
from codeintel_rev.io.splade_manager import SpladeQueryEngine, SpladeQueryOptions

from tests._helpers import assertions
from tests.fixtures.build_tiny_indices import build_tiny_bm25_index, build_tiny_impact_index

pytest.importorskip("pyserini", reason="requires pyserini for Lucene smoke tests")


def test_bm25_multifield_smoke(tmp_path: Path) -> None:
    """Ensure the BM25 helper produces a searchable Lucene index."""
    index_dir = build_tiny_bm25_index(tmp_path)
    engine = BM25QueryEngine(index_dir)
    opts = BM25QueryOptions(top_k=5, field_weights={"contents": 1.0})
    hits = engine.search("hybrid sparse fusion", options=opts)
    assertions.expect_true(isinstance(hits, list))
    assertions.expect_true(bool(hits))


def test_splade_impact_smoke(tmp_path: Path) -> None:
    """Ensure the impact helper produces a searchable SPLADE index."""
    index_dir = build_tiny_impact_index(tmp_path)
    engine = SpladeQueryEngine(index_dir, encoder="splade")
    hits = engine.search("splade impact search", options=SpladeQueryOptions(top_k=5))
    assertions.expect_true(isinstance(hits, list))
    assertions.expect_true(bool(hits))
