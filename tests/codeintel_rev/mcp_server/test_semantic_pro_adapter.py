"""Regression tests for the refactored semantic_pro adapter."""

from __future__ import annotations

import contextlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, ClassVar, cast

import pytest
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.config.api import SearchSettings
from codeintel_rev.mcp_server.adapters import semantic_pro
from codeintel_rev.mcp_server.schemas import Finding
from codeintel_rev.retrieval.pipeline.gating import StageDecision
from codeintel_rev.retrieval.pipeline.late_interaction import LateInteractionResult
from codeintel_rev.retrieval.pipeline.rerankers import RerankResult
from codeintel_rev.retrieval.pipeline.stage0 import Stage0Options, Stage0Result

from tests._helpers import assertions

if TYPE_CHECKING:  # pragma: no cover - typing only
    from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
    from codeintel_rev.io.hybrid_search import HybridSearchEngine

_SECOND_STAGE_CHUNK_ID = 2
_RERANKED_CHUNK_ID = 4


@dataclass(slots=True)
class _Stage0Expectation:
    limit: int | None = None
    options: Stage0Options | None = None


class _StubContext:
    HYBRID_WEIGHTS: ClassVar[dict[str, float]] = {
        "bm25": 0.5,
        "splade": 0.25,
        "semantic": 0.25,
    }

    SEARCH_SETTINGS: ClassVar[SearchSettings] = SearchSettings(
        bm25_weight=0.5,
        splade_weight=0.25,
        faiss_weight=0.25,
        per_channel_k=90,
        fusion_k=45,
        rrf_base=75,
        max_results=30,
    )

    app_config = SimpleNamespace(search=SEARCH_SETTINGS)

    @staticmethod
    def get_hybrid_engine() -> object:  # pragma: no cover - patched run_stage0 ignores
        return object()

    @staticmethod
    def open_catalog() -> contextlib.AbstractContextManager[object]:
        return contextlib.nullcontext(object())

    @staticmethod
    def get_xtr_index() -> None:  # pragma: no cover - adapters patch resolver
        return None

    @staticmethod
    def ensure_faiss_ready() -> tuple[bool, list[str], str | None]:  # pragma: no cover
        return True, [], None

    @staticmethod
    def hybrid_fusion_weights() -> Mapping[str, float]:
        return {
            "bm25": float(_StubContext.SEARCH_SETTINGS.bm25_weight),
            "splade": float(_StubContext.SEARCH_SETTINGS.splade_weight),
            "semantic": float(_StubContext.SEARCH_SETTINGS.faiss_weight),
        }

    @staticmethod
    def hybrid_search_settings() -> SearchSettings:
        return _StubContext.SEARCH_SETTINGS

    @staticmethod
    def clamp_hybrid_limit(candidate: int) -> int:
        max_results = int(_StubContext.SEARCH_SETTINGS.max_results)
        return max(1, min(int(candidate), max_results))

    @staticmethod
    def build_stage0_options(*, weights: Mapping[str, float]) -> Stage0Options:
        return Stage0Options(
            weights=dict(weights),
            per_channel_k=_StubContext.SEARCH_SETTINGS.per_channel_k,
            fusion_k=_StubContext.SEARCH_SETTINGS.fusion_k,
            rrf_base=_StubContext.SEARCH_SETTINGS.rrf_base,
        )


def _build_pro_hooks(
    *,
    stage0: Stage0Result,
    decision: StageDecision,
    findings: list[Finding],
    expected_weights: Mapping[str, float] | None = None,
    expectation: _Stage0Expectation | None = None,
) -> semantic_pro.SemanticProHooks:
    base = semantic_pro.SemanticProHooks.default()

    def _run_stage0(
        engine: HybridSearchEngine,
        *,
        query: str,
        semantic_hits: Sequence[tuple[int, float]] | None,
        limit: int,
        options: Stage0Options | None = None,
    ) -> Stage0Result:
        del engine, query, semantic_hits
        if expectation and expectation.limit is not None:
            assertions.expect_equal(limit, expectation.limit)
        weights = expected_weights or _StubContext.HYBRID_WEIGHTS
        if options is None or options.weights is None:
            pytest.fail("hybrid weights not provided to Stage0")
        assertions.expect_equal(dict(options.weights), dict(weights))
        if expectation and expectation.options is not None:
            assertions.expect_equal(options.per_channel_k, expectation.options.per_channel_k)
            assertions.expect_equal(options.fusion_k, expectation.options.fusion_k)
            assertions.expect_equal(options.rrf_base, expectation.options.rrf_base)
        return stage0

    def _hydrate(
        catalog: DuckDBCatalog,
        ids: Sequence[int],
        scores: Sequence[float],
    ) -> list[Finding]:
        del catalog, ids, scores
        return findings

    def _decide(
        signals: Mapping[str, object], config: semantic_pro.StageGateConfig
    ) -> StageDecision:
        del signals, config
        return decision

    return replace(
        base,
        run_stage0=_run_stage0,
        decide_secondary_stage=_decide,
        hydrate_ids=_hydrate,
    )


@pytest.mark.asyncio
async def test_semantic_search_pro_returns_findings() -> None:
    """semantic_search_pro orchestrates Stage-0 and returns hydrated findings."""
    stage0 = Stage0Result(ids=[1, 2], scores=[0.9, 0.8], warnings=[], method={})
    base_finding: Finding = {"chunk_id": 1, "score": 0.9}
    hooks = _build_pro_hooks(
        stage0=stage0,
        decision=StageDecision(should_run=False, reason="tests"),
        findings=[base_finding],
    )

    context = cast("ApplicationContext", _StubContext())
    envelope = await semantic_pro.semantic_search_pro(context, "query", limit=3, hooks=hooks)
    if "findings" not in envelope:
        pytest.fail("expected findings in envelope")
    assertions.expect_equal(envelope["findings"], [{"chunk_id": 1, "score": 0.9}])
    if "method" not in envelope:
        pytest.fail("expected method metadata")
    method = envelope["method"]
    if "gating" not in method:
        pytest.fail("expected gating metadata")
    gating = method["gating"]
    if "reason" not in gating:
        pytest.fail("expected gating reason")
    assertions.expect_equal(gating["reason"], "tests")


@pytest.mark.asyncio
async def test_semantic_search_pro_runs_late_interaction() -> None:
    """Late-interaction results replace Stage-0 ordering when gate allows."""
    stage0 = Stage0Result(ids=[1, 2], scores=[0.9, 0.8], warnings=[], method={})
    li_finding: Finding = {"chunk_id": _SECOND_STAGE_CHUNK_ID, "score": 1.0}
    hooks = _build_pro_hooks(
        stage0=stage0,
        decision=StageDecision(should_run=True, reason="budget"),
        findings=[li_finding],
    )

    def _late_factory(_index: semantic_pro.XTRIndex) -> semantic_pro.LateInteractionRunner:
        class _StubLateInteraction:
            def rescore(
                self,
                query: str,
                candidate_ids: Sequence[int],
                *,
                explain: bool = False,
            ) -> LateInteractionResult:
                del self, query, candidate_ids, explain
                return LateInteractionResult(ids=[_SECOND_STAGE_CHUNK_ID, 1], scores=[1.0, 0.7])

        del _index
        return _StubLateInteraction()

    def _resolve_stub(_ctx: ApplicationContext) -> semantic_pro.XTRIndex | None:
        del _ctx
        return cast("semantic_pro.XTRIndex", object())

    hooks = replace(
        hooks,
        resolve_xtr_index=_resolve_stub,
        late_interaction_factory=_late_factory,
    )

    context = cast("ApplicationContext", _StubContext())
    envelope = await semantic_pro.semantic_search_pro(context, "query", hooks=hooks)
    if "findings" not in envelope:
        pytest.fail("expected findings in envelope")
    first = envelope["findings"][0]
    if "chunk_id" not in first:
        pytest.fail("expected chunk_id in finding")
    assertions.expect_equal(first["chunk_id"], _SECOND_STAGE_CHUNK_ID)
    if "method" not in envelope:
        pytest.fail("expected method metadata")
    method = envelope["method"]
    if "stages" not in method:
        pytest.fail("expected stage metadata")
    stage = next(
        item for item in method["stages"] if "name" in item and item["name"] == "late_interaction"
    )
    if "status" not in stage:
        pytest.fail("expected stage status")
    assertions.expect_equal(stage["status"], "run")


@pytest.mark.asyncio
async def test_semantic_search_pro_runs_reranker() -> None:
    """Reranker output is honored when enabled in options."""
    stage0 = Stage0Result(ids=[3, 4], scores=[0.4, 0.3], warnings=[], method={})
    rerank_finding: Finding = {"chunk_id": _RERANKED_CHUNK_ID, "score": 0.3}
    hooks = _build_pro_hooks(
        stage0=stage0,
        decision=StageDecision(should_run=False, reason="tests"),
        findings=[rerank_finding],
    )

    class _StubReranker:
        def rerank(
            self,
            query: str,
            ids: Iterable[int],
            scores: Iterable[float],
        ) -> RerankResult:
            del self, query
            ordered_ids = list(ids)
            ordered_scores = list(scores)
            return RerankResult(ids=list(reversed(ordered_ids)), scores=ordered_scores)

    def _build_reranker() -> _StubReranker:
        return _StubReranker()

    hooks = replace(hooks, reranker_factory=_build_reranker)

    options = semantic_pro.ProOptions(use_reranker=True, use_warp=False)
    context = cast("ApplicationContext", _StubContext())
    envelope = await semantic_pro.semantic_search_pro(
        context, "query", options=options, hooks=hooks
    )
    if "findings" not in envelope:
        pytest.fail("expected findings in envelope")
    reranked = envelope["findings"][0]
    if "chunk_id" not in reranked:
        pytest.fail("expected chunk_id in finding")
    assertions.expect_equal(reranked["chunk_id"], _RERANKED_CHUNK_ID)
    if "method" not in envelope:
        pytest.fail("expected method metadata")
    method = envelope["method"]
    if "reranker" not in method:
        pytest.fail("expected reranker metadata")
    reranker = method["reranker"]
    if "enabled" not in reranker:
        pytest.fail("expected reranker enabled flag")
    assertions.expect_true(reranker["enabled"])


@pytest.mark.asyncio
async def test_semantic_search_pro_respects_stage_weights_option() -> None:
    """SemanticProOptions.stage_weights overrides default hybrid weights."""
    stage0 = Stage0Result(ids=[1], scores=[0.5], warnings=[], method={})
    custom_weights = {"bm25": 2.0, "semantic": 3.0}
    hooks = _build_pro_hooks(
        stage0=stage0,
        decision=StageDecision(should_run=False, reason="tests"),
        findings=[{"chunk_id": 1, "score": 0.5}],
        expected_weights=custom_weights,
    )
    context = cast("ApplicationContext", _StubContext())
    options = semantic_pro.SemanticProOptions(stage_weights=custom_weights)
    await semantic_pro.semantic_search_pro(context, "query", options=options, hooks=hooks)


@pytest.mark.asyncio
async def test_semantic_search_pro_clamps_limit_and_stage0_settings() -> None:
    """Stage-0 options derive from AppConfig search settings in semantic_pro."""
    stage0 = Stage0Result(ids=[], scores=[], warnings=[], method={})
    expected_options = Stage0Options(
        weights=dict(_StubContext.HYBRID_WEIGHTS),
        per_channel_k=_StubContext.SEARCH_SETTINGS.per_channel_k,
        fusion_k=_StubContext.SEARCH_SETTINGS.fusion_k,
        rrf_base=_StubContext.SEARCH_SETTINGS.rrf_base,
    )
    hooks = _build_pro_hooks(
        stage0=stage0,
        decision=StageDecision(should_run=False, reason="tests"),
        findings=[],
        expectation=_Stage0Expectation(
            limit=_StubContext.SEARCH_SETTINGS.max_results,
            options=expected_options,
        ),
    )
    context = cast("ApplicationContext", _StubContext())
    envelope = await semantic_pro.semantic_search_pro(context, "query", limit=500, hooks=hooks)
    limits = envelope.get("limits")
    if limits is None:
        pytest.fail("expected limits array")
    assertions.expect_equal(
        limits,
        [f"k={_StubContext.SEARCH_SETTINGS.max_results}"],
    )
