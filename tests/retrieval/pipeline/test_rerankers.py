"""Tests for reranker pipeline components."""

from __future__ import annotations

from codeintel_rev.retrieval.pipeline import Doc, NoopReranker

from tests._helpers import assertions


def test_noop_reranker_preserves_order() -> None:
    """Test that no-op reranker preserves document order."""
    reranker = NoopReranker()
    docs = [Doc(id=1, snippet="a"), Doc(id=2, snippet="b")]

    result = reranker.rerank("query", docs)

    assertions.expect_sequence_equal(result.ids, [1, 2])
    assertions.expect_sequence_equal(result.scores, [0.0, 0.0])
