"""Regression tests for the thin semantic adapter."""

from __future__ import annotations

import contextlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, ClassVar, cast

import pytest
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.config.api import SearchSettings
from codeintel_rev.mcp_server.adapters import semantic as semantic_adapter
from codeintel_rev.mcp_server.schemas import Finding
from codeintel_rev.retrieval.pipeline.gating import StageDecision
from codeintel_rev.retrieval.pipeline.stage0 import Stage0Options, Stage0Result

from tests._helpers import assertions

if TYPE_CHECKING:  # pragma: no cover - typing only
    from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
    from codeintel_rev.io.hybrid_search import HybridSearchEngine


@dataclass(slots=True)
class _Stage0Expectation:
    limit: int | None = None
    options: Stage0Options | None = None


class _StubContext:
    HYBRID_WEIGHTS: ClassVar[dict[str, float]] = {"bm25": 0.4, "splade": 0.3, "semantic": 0.3}

    SEARCH_SETTINGS: ClassVar[SearchSettings] = SearchSettings(
        bm25_weight=0.4,
        splade_weight=0.3,
        faiss_weight=0.3,
        per_channel_k=75,
        fusion_k=40,
        rrf_base=55,
        max_results=25,
    )

    app_config = SimpleNamespace(search=SEARCH_SETTINGS)

    @staticmethod
    def get_hybrid_engine() -> object:  # pragma: no cover - patched run_stage0 ignores
        return object()

    @staticmethod
    def open_catalog() -> contextlib.AbstractContextManager[object]:
        return contextlib.nullcontext(object())

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

    runtime_cells = type("_Cells", (), {"xtr_index": object()})()  # pragma: no cover


def _build_runtime_hooks(
    *,
    stage0: Stage0Result,
    findings: list[Finding],
    decision: StageDecision,
    expected_weights: Mapping[str, float] | None = None,
    expectation: _Stage0Expectation | None = None,
) -> semantic_adapter.SemanticRuntimeHooks:
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
        signals: Mapping[str, object], config: semantic_adapter.StageGateConfig
    ) -> StageDecision:
        del signals, config
        return decision

    return semantic_adapter.SemanticRuntimeHooks(
        run_stage0=_run_stage0,
        decide_secondary_stage=_decide,
        hydrate_findings=_hydrate,
    )


@pytest.mark.asyncio
async def test_semantic_search_returns_findings() -> None:
    """semantic_search hydrates catalog rows and surfaces method metadata."""
    stage0 = Stage0Result(
        ids=[1, 2], scores=[0.9, 0.8], warnings=["fanout"], method={"engine": "stub"}
    )
    sample_finding: Finding = {"chunk_id": 1, "score": 0.9}
    hooks = _build_runtime_hooks(
        stage0=stage0,
        findings=[sample_finding],
        decision=StageDecision(should_run=False, reason="tests"),
    )

    context = cast("ApplicationContext", _StubContext())
    envelope = await semantic_adapter.semantic_search(context, "vector", limit=5, hooks=hooks)

    if "confidence" not in envelope:
        pytest.fail("expected confidence in envelope")
    assertions.expect_almost_equal(envelope["confidence"], 0.9)
    if "findings" not in envelope:
        pytest.fail("expected findings in envelope")
    assertions.expect_equal(envelope["findings"], [{"chunk_id": 1, "score": 0.9}])
    if "method" not in envelope:
        pytest.fail("expected method metadata")
    method = envelope["method"]
    if "notes" not in method:
        pytest.fail("expected method notes")
    assertions.expect_equal(method["notes"], ["fanout"])
    limits = envelope.get("limits")
    if limits is None:
        pytest.fail("expected limits array")
    assertions.expect_equal(limits, ["k=5"])


@pytest.mark.asyncio
async def test_semantic_search_clamps_limit_and_applies_stage0_settings() -> None:
    """Stage-0 options derive from AppConfig search settings."""
    stage0 = Stage0Result(ids=[], scores=[], warnings=[], method={})
    expected_options = Stage0Options(
        weights=dict(_StubContext.HYBRID_WEIGHTS),
        per_channel_k=_StubContext.SEARCH_SETTINGS.per_channel_k,
        fusion_k=_StubContext.SEARCH_SETTINGS.fusion_k,
        rrf_base=_StubContext.SEARCH_SETTINGS.rrf_base,
    )
    hooks = _build_runtime_hooks(
        stage0=stage0,
        findings=[],
        decision=StageDecision(should_run=False, reason="tests"),
        expectation=_Stage0Expectation(
            limit=_StubContext.SEARCH_SETTINGS.max_results,
            options=expected_options,
        ),
    )
    context = cast("ApplicationContext", _StubContext())
    envelope = await semantic_adapter.semantic_search(context, "vector", limit=999, hooks=hooks)
    limits = envelope.get("limits")
    if limits is None:
        pytest.fail("expected limits array")
    assertions.expect_equal(limits, [f"k={_StubContext.SEARCH_SETTINGS.max_results}"])


@pytest.mark.asyncio
async def test_semantic_search_rejects_empty_query() -> None:
    """Empty queries return an error envelope without calling the engine."""
    context = cast("ApplicationContext", _StubContext())
    envelope = await semantic_adapter.semantic_search(context, " \t", limit=2)
    assertions.expect_in("error", envelope)
