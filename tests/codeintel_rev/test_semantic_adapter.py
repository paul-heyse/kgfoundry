"""Regression tests for the thin semantic adapter."""

from __future__ import annotations

import contextlib
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, cast

import pytest
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.mcp_server.adapters import semantic as semantic_adapter
from codeintel_rev.mcp_server.schemas import Finding
from codeintel_rev.retrieval.pipeline.gating import StageDecision
from codeintel_rev.retrieval.pipeline.stage0 import Stage0Options, Stage0Result

from tests._helpers import assertions

if TYPE_CHECKING:  # pragma: no cover - typing only
    from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
    from codeintel_rev.io.hybrid_search import HybridSearchEngine


class _StubContext:
    @staticmethod
    def get_hybrid_engine() -> object:  # pragma: no cover - patched run_stage0 ignores
        return object()

    @staticmethod
    def open_catalog() -> contextlib.AbstractContextManager[object]:
        return contextlib.nullcontext(object())

    @staticmethod
    def ensure_faiss_ready() -> tuple[bool, list[str], str | None]:  # pragma: no cover
        return True, [], None

    runtime_cells = type("_Cells", (), {"xtr_index": object()})()  # pragma: no cover


def _build_runtime_hooks(
    *,
    stage0: Stage0Result,
    findings: list[Finding],
    decision: StageDecision,
) -> semantic_adapter.SemanticRuntimeHooks:
    def _run_stage0(
        engine: HybridSearchEngine,
        *,
        query: str,
        semantic_hits: Sequence[tuple[int, float]] | None,
        limit: int,
        options: Stage0Options | None = None,
    ) -> Stage0Result:
        del engine, query, semantic_hits, limit, options
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
    if "limits" not in envelope:
        pytest.fail("expected limits array")
    assertions.expect_equal(envelope["limits"], ["k=5"])


@pytest.mark.asyncio
async def test_semantic_search_rejects_empty_query() -> None:
    """Empty queries return an error envelope without calling the engine."""
    context = cast("ApplicationContext", _StubContext())
    envelope = await semantic_adapter.semantic_search(context, " \t", limit=2)
    assertions.expect_in("error", envelope)
