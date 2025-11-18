"""Tests for Stage-0 hybrid retrieval pipeline."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from codeintel_rev.io.hybrid_search import HybridSearchResult
from codeintel_rev.retrieval.pipeline.stage0 import Stage0Options, Stage0Result, run_stage0
from codeintel_rev.retrieval.types import HybridResultDoc

from tests._helpers import assertions


@dataclass
class _StubHybridEngine:
    result: HybridSearchResult

    def search(
        self,
        query: str,
        semantic_hits: Sequence[tuple[int, float]],
        limit: int,
        options: Stage0Options | None,
    ) -> HybridSearchResult:
        self.last_query = query
        self.last_semantic_hits = list(semantic_hits)
        self.last_limit = limit
        self.last_options = options
        return self.result


def test_run_stage0_normalizes_hybrid_output() -> None:
    """Test that run_stage0 normalizes hybrid search engine outputs."""
    hybrid_result = HybridSearchResult(
        docs=[
            HybridResultDoc(doc_id="1", score=0.9),
            HybridResultDoc(doc_id="2", score=0.8),
        ],
        contributions={"1": [("semantic", 0, 0.9)], "2": [("bm25", 0, 0.8)]},
        channels=["semantic", "bm25"],
        warnings=["bm25_timeout"],
        method={"fusion": "rrf"},
    )
    engine = _StubHybridEngine(result=hybrid_result)

    result = run_stage0(
        engine,
        query="vector search",
        semantic_hits=[(1, 0.9), (2, 0.8)],
        limit=5,
        options=Stage0Options(weights={"semantic": 1.0}),
    )

    assertions.expect_true(isinstance(result, Stage0Result))
    assertions.expect_sequence_equal(result.ids, [1, 2])
    assertions.expect_sequence_equal(result.scores, [0.9, 0.8])
    assertions.expect_sequence_equal(result.warnings, ["bm25_timeout"])
    assertions.expect_equal(result.method, {"fusion": "rrf"})
    assertions.expect_sequence_equal(result.channels, ["semantic", "bm25"])
    assertions.expect_equal(
        result.contributions,
        {1: [("semantic", 0, 0.9)], 2: [("bm25", 0, 0.8)]},
    )


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
        engine,
        query="options-test",
        semantic_hits=[(10, 0.42)],
        limit=3,
        options=options,
    )

    assertions.expect_sequence_equal(result.ids, [10])
    assertions.expect_equal(engine.last_options.weights, {"semantic": 2.0})
    assertions.expect_equal(engine.last_options.extra_channels, {"warp": []})


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
    result = run_stage0(engine, query="nothing", semantic_hits=[], limit=1)

    assertions.expect_sequence_equal(result.ids, [])
    assertions.expect_sequence_equal(result.scores, [])
    assertions.expect_equal(result.contributions, None)
