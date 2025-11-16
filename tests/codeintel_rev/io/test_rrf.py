"""Tests for the weighted reciprocal rank fusion helpers."""

from __future__ import annotations

import pytest
from codeintel_rev.io.rrf import weighted_rrf

from tests._helpers import assertions


def test_weighted_rrf_combines_channels() -> None:
    """RRF fusion combines channel contributions and respects weights."""
    fused_ids, contributions, scores = weighted_rrf(
        {
            "coderank": [(1, 0.9), (2, 0.8)],
            "warp": [(2, 0.95)],
        },
        weights={"coderank": 1.0, "warp": 2.0},
        k=60,
        top_k=2,
    )

    assertions.expect_sequence_equal(fused_ids, [2, 1])
    assertions.expect_true(scores[2] > scores[1])
    channel_names = [entry[0] for entry in contributions[2]]
    assertions.expect_in("warp", channel_names)
    assertions.expect_in("coderank", channel_names)


def test_weighted_rrf_rejects_invalid_topk() -> None:
    """`top_k` must be positive."""
    with pytest.raises(ValueError, match="top_k"):
        weighted_rrf({"coderank": []}, weights={"coderank": 1.0}, k=60, top_k=0)


def test_weighted_rrf_applies_minmax_normalization() -> None:
    """Normalization scales contributions to the [0, 1] range."""
    _, contributions, _scores = weighted_rrf(
        {"coderank": [(1, 10.0), (2, 11.0)]},
        weights={"coderank": 1.0},
        k=60,
        top_k=2,
        normalize="minmax",
    )
    coderank_entries = {doc_id: contribs[0][2] for doc_id, contribs in contributions.items()}
    assertions.expect_equal(coderank_entries[1], 0.0)
    assertions.expect_equal(coderank_entries[2], 1.0)
