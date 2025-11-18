"""Tests for Stage-0 hybrid retrieval pipeline."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

import pytest
from codeintel_rev.io.hybrid_search import (
    HybridSearchEngine,
    HybridSearchOptions,
    HybridSearchResult,
)
from codeintel_rev.retrieval.pipeline.stage0 import (
    Stage0ChannelHit,
    Stage0Options,
    Stage0Result,
    run_stage0,
)
from codeintel_rev.retrieval.types import HybridResultDoc, SearchHit

from tests._helpers import assertions


@dataclass
class _StubHybridEngine:
    result: HybridSearchResult
    last_query: str | None = None
    last_semantic_hits: list[tuple[int, float]] | None = None
    last_limit: int | None = None
    last_options: HybridSearchOptions | None = None

    def search(
        self,
        query: str,
        semantic_hits: Sequence[tuple[int, float]],
        limit: int,
        options: HybridSearchOptions | None,
    ) -> HybridSearchResult:
        self.last_query = query
        self.last_semantic_hits = list(semantic_hits)
        self.last_limit = limit
        self.last_options = options
        return self.result


@pytest.mark.parametrize("case", ["with-data", "empty"])
def test_run_stage0_normalizes_hybrid_output(case: str) -> None:
    """Stage-0 normalizes doc IDs and contribution envelopes."""
    if case == "with-data":
        raw_contributions: dict[str, list[tuple[str, int, float]]] = {"1": [("semantic", 0, 0.9)]}
        expected: dict[int, list[tuple[str, int, float]]] | None = {1: [("semantic", 0, 0.9)]}
        docs = [HybridResultDoc(doc_id="1", score=0.9)]
    else:
        raw_contributions = {}
        expected = None
        docs = []

    hybrid_result = HybridSearchResult(
        docs=docs,
        contributions=raw_contributions,
        channels=["semantic", "bm25"],
        warnings=["bm25_timeout"],
        method={"fusion": "rrf"},
    )
    engine = _StubHybridEngine(result=hybrid_result)

    result = run_stage0(
        cast("HybridSearchEngine", engine),
        query="vector search",
        semantic_hits=[(1, 0.9)],
        limit=5,
        options=Stage0Options(weights={"semantic": 1.0}),
    )

    assertions.expect_true(isinstance(result, Stage0Result))
    assertions.expect_equal(result.contributions, expected)


def test_run_stage0_respects_options_passed_from_adapter() -> None:
    """Test that run_stage0 respects options passed from adapter."""
    hybrid_result = HybridSearchResult(
        docs=[HybridResultDoc(doc_id="10", score=0.42)],
        contributions={},
        channels=["semantic"],
        warnings=[],
        method={},
    )
    engine = _StubHybridEngine(result=hybrid_result)
    options = Stage0Options(weights={"semantic": 2.0}, extra_channels={"warp": []})

    result = run_stage0(
        cast("HybridSearchEngine", engine),
        query="options-test",
        semantic_hits=[(10, 0.42)],
        limit=3,
        options=options,
    )

    assertions.expect_sequence_equal(result.ids, [10])
    last_options = engine.last_options
    if last_options is None:
        pytest.fail("Stage-0 engine options were not captured")
    assertions.expect_equal(last_options.weights, {"semantic": 2.0})
    assertions.expect_equal(last_options.extra_channels, {"warp": []})


def test_run_stage0_handles_empty_docs() -> None:
    """Test that run_stage0 handles empty document results gracefully."""
    hybrid_result = HybridSearchResult(
        docs=[],
        contributions={},
        channels=["semantic"],
        warnings=["empty"],
        method={},
    )
    engine = _StubHybridEngine(result=hybrid_result)
    result = run_stage0(
        cast("HybridSearchEngine", engine), query="nothing", semantic_hits=[], limit=1
    )

    assertions.expect_sequence_equal(result.ids, [])
    assertions.expect_sequence_equal(result.scores, [])
    assertions.expect_equal(result.contributions, None)


@pytest.mark.parametrize("hit_factory", ["dataclass", "tuple"])
def test_run_stage0_normalizes_extra_channel_hits(hit_factory: str) -> None:
    """Extra channel payloads are converted into SearchHit instances."""
    hybrid_result = HybridSearchResult(
        docs=[HybridResultDoc(doc_id="99", score=0.5)],
        contributions={},
        channels=["semantic"],
        warnings=[],
        method={},
    )
    engine = _StubHybridEngine(result=hybrid_result)
    extra_hit: Stage0ChannelHit | tuple[str, int, float]
    if hit_factory == "dataclass":
        extra_hit = Stage0ChannelHit(doc_id="777", rank=0, score=0.75)
    else:
        extra_hit = ("888", 1, 0.65)
    options = Stage0Options(extra_channels={"warp": [extra_hit]})

    run_stage0(
        cast("HybridSearchEngine", engine),
        query="normalize",
        semantic_hits=[(99, 0.5)],
        limit=1,
        options=options,
    )

    last_options = engine.last_options
    if last_options is None:
        pytest.fail("Stage-0 engine options were not captured")
    extra_channels = last_options.extra_channels
    if extra_channels is None:
        pytest.fail("Stage-0 options missing extra channel metadata")
    warp_hits = extra_channels["warp"]
    assertions.expect_true(isinstance(warp_hits[0], SearchHit))
    assertions.expect_equal(warp_hits[0].source, "warp")
