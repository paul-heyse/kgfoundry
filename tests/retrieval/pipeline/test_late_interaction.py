"""Tests for late-interaction rescoring pipeline components."""

from __future__ import annotations

from collections.abc import Iterable
from typing import cast

from codeintel_rev.io.xtr_manager import XTRIndex
from codeintel_rev.retrieval.pipeline.late_interaction import (
    LateInteractionResult,
    XTRLateInteraction,
)

from tests._helpers import assertions


class _StubXTRIndex:
    def __init__(self, triples: list[tuple[int, float, dict[str, object] | None]]) -> None:
        self._triples = triples

    def rescore(
        self,
        *,
        query: str,
        candidate_chunk_ids: Iterable[int],
        explain: bool,
        topk_explanations: int,
    ) -> list[tuple[int, float, dict[str, object] | None]]:
        self.last_query = query
        self.last_candidates = list(candidate_chunk_ids)
        self.last_explain = explain
        self.last_topk = topk_explanations
        return self._triples


def test_xtr_late_interaction_rescore() -> None:
    """Test XTR late-interaction rescoring produces correct results."""
    triples: list[tuple[int, float, dict[str, object] | None]] = [
        (
            1,
            0.9,
            cast(
                "dict[str, object]",
                {"token_matches": [{"q_index": 0, "doc_index": 1, "similarity": 0.9}]},
            ),
        ),
        (2, 0.8, None),
    ]
    index = _StubXTRIndex(triples=triples)
    li = XTRLateInteraction(index=cast("XTRIndex", index))

    result = li.rescore(
        query="vector search",
        candidate_ids=[1, 2],
        explain=True,
        topk_explanations=3,
    )

    assertions.expect_true(isinstance(result, LateInteractionResult))
    assertions.expect_sequence_equal(result.ids, [1, 2])
    assertions.expect_sequence_equal(result.scores, [0.9, 0.8])
    assertions.expect_equal(
        result.explanations,
        [(1, {"token_matches": [{"doc_index": 1, "q_index": 0, "similarity": 0.9}]})],
    )
