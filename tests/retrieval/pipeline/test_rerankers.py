"""Tests for reranker pipeline components."""

from __future__ import annotations

from codeintel_rev.retrieval.pipeline.rerankers import NoopReranker

from tests._helpers import assertions


def test_noop_reranker_preserves_order() -> None:
    """No-op reranker returns ids/scores unchanged."""
    reranker = NoopReranker()
    result = reranker.rerank("query", ids=[1, 2], scores=[0.9, 0.7])

    assertions.expect_sequence_equal(result.ids, [1, 2])
    assertions.expect_sequence_equal(result.scores, [0.9, 0.7])
