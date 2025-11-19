"""Tests for Stage-0 hybrid retrieval pipeline."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import pytest
from codeintel_rev.io.hybrid_search import HybridSearchEngine, HybridSearchOptions
from codeintel_rev.retrieval.pipeline.stage0 import Stage0Options, Stage0Result, run_stage0
from codeintel_rev.retrieval.types import HybridResultDoc, HybridSearchResult

from tests._helpers import assertions


class _StubHybridEngine:
    def __init__(self, result: HybridSearchResult) -> None:
        self.result = result
        self.last_query: str | None = None
        self.last_semantic_hits: list[tuple[int, float]] | None = None
        self.last_limit: int | None = None
        self.last_options: HybridSearchOptions | None = None

    def search(
        self,
        query: str,
        *,
        semantic_hits: Sequence[tuple[int, float]],
        limit: int,
        options: HybridSearchOptions | None = None,
    ) -> HybridSearchResult:
        self.last_query = query
        self.last_semantic_hits = list(semantic_hits)
        self.last_limit = limit
        self.last_options = options
        return self.result


@pytest.mark.parametrize("docs", [[HybridResultDoc(doc_id="1", score=0.9)], []])
def test_run_stage0_normalizes_output(docs: list[HybridResultDoc]) -> None:
    """Stage-0 normalizes doc IDs and warnings regardless of doc payload."""
    hybrid_result = HybridSearchResult(
        docs=docs,
        contributions={},
        channels=["semantic"],
        warnings=["fanout"],
        method={"engine": "stub"},
    )
    engine = _StubHybridEngine(result=hybrid_result)

    result = run_stage0(
        cast("HybridSearchEngine", engine),
        query="vector search",
        semantic_hits=[(10, 0.95)],
        limit=5,
        options=Stage0Options(weights={"semantic": 1.0}),
    )

    assertions.expect_true(isinstance(result, Stage0Result))
    assertions.expect_sequence_equal(result.ids, [int(doc.doc_id) for doc in docs])
    assertions.expect_sequence_equal(result.warnings, ["fanout"])
    if engine.last_options is None:
        pytest.fail("Stage-0 engine options were not captured")
    assertions.expect_equal(engine.last_options.weights, {"semantic": 1.0})


def test_run_stage0_handles_empty_options() -> None:
    """Stage-0 falls back to default options when none were provided."""
    hybrid_result = HybridSearchResult(
        docs=[HybridResultDoc(doc_id="5", score=0.5)],
        contributions={},
        channels=["semantic"],
        warnings=[],
        method={},
    )
    engine = _StubHybridEngine(result=hybrid_result)

    result = run_stage0(
        cast("HybridSearchEngine", engine),
        query="noop",
        semantic_hits=[],
        limit=1,
    )

    assertions.expect_sequence_equal(result.ids, [5])
    if engine.last_options is None:
        pytest.fail("Stage-0 should construct default options")


def test_run_stage0_clamps_options_to_limit() -> None:
    """Stage-0 clamps fusion/per-channel budgets to the requested limit."""
    hybrid_result = HybridSearchResult(
        docs=[HybridResultDoc(doc_id="7", score=0.7)],
        contributions={},
        channels=["semantic"],
        warnings=[],
        method={},
    )
    engine = _StubHybridEngine(result=hybrid_result)

    custom_options = Stage0Options(
        weights={"semantic": 1.0},
        per_channel_k=2,
        fusion_k=10,
        rrf_base=70,
    )
    _ = run_stage0(
        cast("HybridSearchEngine", engine),
        query="clamp",
        semantic_hits=[],
        limit=3,
        options=custom_options,
    )
    if engine.last_options is None:
        pytest.fail("Stage-0 should pass options to the engine")
    assertions.expect_equal(engine.last_options.fusion_k, 3)
    assertions.expect_equal(engine.last_options.per_channel_k, 3)
