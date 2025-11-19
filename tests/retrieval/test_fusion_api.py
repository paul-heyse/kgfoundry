"""Unit tests for the pure fusion API entrypoints."""

from __future__ import annotations

from codeintel_rev.retrieval.fusion.api import FusionInput, FusionOptions, RRFWeighter

from tests._helpers import assertions


def test_rrf_weighter_fuses_multiple_channels() -> None:
    """Ensure the RRF weighter returns typed fused tuples."""
    inputs = [
        FusionInput(channel="bm25", candidates=[(1, 3.0), (2, 1.0)]),
        FusionInput(channel="splade", candidates=[(2, 2.5), (3, 0.8)]),
        FusionInput(channel="semantic", candidates=[(4, 4.2)]),
    ]
    options = FusionOptions(weights={"bm25": 1.0, "splade": 0.5, "semantic": 1.5}, k=3, base=50)

    fused = RRFWeighter().fuse(inputs, options=options)

    assertions.expect_equal(len(fused), 3)
    for doc_id, score in fused:
        assertions.expect_true(isinstance(doc_id, int))
        assertions.expect_true(isinstance(score, float))


def test_rrf_weighter_handles_empty_candidates() -> None:
    """RRF fusion should tolerate empty channel input."""
    inputs = [
        FusionInput(channel="bm25", candidates=[]),
        FusionInput(channel="splade", candidates=[(12, 0.7)]),
    ]
    fused = RRFWeighter().fuse(inputs, options=FusionOptions(k=2))

    assertions.expect_equal(len(fused), 1)
    doc_id, score = fused[0]
    assertions.expect_equal(doc_id, 12)
    assertions.expect_almost_equal(score, 1.0 / 61.0)
