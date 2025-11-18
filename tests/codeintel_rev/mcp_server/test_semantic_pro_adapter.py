"""Regression tests for the refactored semantic_pro adapter."""

from __future__ import annotations

import contextlib
from collections.abc import Iterable, Sequence
from typing import cast

import pytest
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.mcp_server.adapters import semantic_pro
from codeintel_rev.retrieval.pipeline.gating import StageDecision
from codeintel_rev.retrieval.pipeline.late_interaction import LateInteractionResult
from codeintel_rev.retrieval.pipeline.rerankers import RerankResult
from codeintel_rev.retrieval.pipeline.stage0 import Stage0Result

from tests._helpers import assertions

_SECOND_STAGE_CHUNK_ID = 2
_RERANKED_CHUNK_ID = 4


class _StubContext:
    @staticmethod
    def get_hybrid_engine() -> object:  # pragma: no cover - patched run_stage0 ignores
        return object()

    @staticmethod
    def open_catalog() -> contextlib.AbstractContextManager[object]:
        return contextlib.nullcontext(object())

    @staticmethod
    def get_xtr_index() -> None:  # pragma: no cover - adapters patch resolver
        return None


@pytest.mark.asyncio
async def test_semantic_search_pro_returns_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    """semantic_search_pro orchestrates Stage-0 and returns hydrated findings."""
    stage0 = Stage0Result(ids=[1, 2], scores=[0.9, 0.8], warnings=[], method={})
    monkeypatch.setattr(semantic_pro, "run_stage0", lambda *_args, **_kwargs: stage0)
    monkeypatch.setattr(
        semantic_pro,
        "decide_secondary_stage",
        lambda *_args, **_kwargs: StageDecision(should_run=False, reason="tests"),
    )
    monkeypatch.setattr(
        semantic_pro,
        "_hydrate_ids",
        lambda *_args, **_kwargs: [{"chunk_id": 1, "score": 0.9}],
    )

    context = cast("ApplicationContext", _StubContext())
    envelope = await semantic_pro.semantic_search_pro(context, "query", limit=3)
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
async def test_semantic_search_pro_runs_late_interaction(monkeypatch: pytest.MonkeyPatch) -> None:
    """Late-interaction results replace Stage-0 ordering when gate allows."""
    stage0 = Stage0Result(ids=[1, 2], scores=[0.9, 0.8], warnings=[], method={})
    monkeypatch.setattr(semantic_pro, "run_stage0", lambda *_args, **_kwargs: stage0)
    monkeypatch.setattr(
        semantic_pro,
        "decide_secondary_stage",
        lambda *_args, **_kwargs: StageDecision(should_run=True, reason="budget"),
    )

    def _fake_rescore(
        _self: semantic_pro.XTRLateInteraction,
        query: str,
        candidate_ids: Sequence[int],
        *,
        explain: bool = False,
    ) -> LateInteractionResult:
        del explain, query, candidate_ids
        return LateInteractionResult(ids=[_SECOND_STAGE_CHUNK_ID, 1], scores=[1.0, 0.7])

    monkeypatch.setattr(semantic_pro.XTRLateInteraction, "rescore", _fake_rescore)
    monkeypatch.setattr(
        semantic_pro,
        "_hydrate_ids",
        lambda *_args, **_kwargs: [{"chunk_id": _SECOND_STAGE_CHUNK_ID, "score": 1.0}],
    )

    monkeypatch.setattr(semantic_pro, "_resolve_xtr_index", lambda *_args: object())

    context = cast("ApplicationContext", _StubContext())
    envelope = await semantic_pro.semantic_search_pro(context, "query")
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
async def test_semantic_search_pro_runs_reranker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reranker output is honored when enabled in options."""
    stage0 = Stage0Result(ids=[3, 4], scores=[0.4, 0.3], warnings=[], method={})
    monkeypatch.setattr(semantic_pro, "run_stage0", lambda *_args, **_kwargs: stage0)
    monkeypatch.setattr(
        semantic_pro,
        "decide_secondary_stage",
        lambda *_args, **_kwargs: StageDecision(should_run=False, reason="tests"),
    )

    class _StubReranker(semantic_pro.NoopReranker):
        @staticmethod
        def rerank(
            _query: str,
            ids: Iterable[int],
            scores: Iterable[float],
        ) -> RerankResult:
            ordered_ids = list(ids)
            ordered_scores = list(scores)
            return RerankResult(ids=list(reversed(ordered_ids)), scores=ordered_scores)

    monkeypatch.setattr(semantic_pro, "NoopReranker", _StubReranker)
    monkeypatch.setattr(
        semantic_pro,
        "_hydrate_ids",
        lambda *_args, **_kwargs: [{"chunk_id": _RERANKED_CHUNK_ID, "score": 0.3}],
    )

    options = semantic_pro.ProOptions(use_reranker=True, use_warp=False)
    context = cast("ApplicationContext", _StubContext())
    envelope = await semantic_pro.semantic_search_pro(context, "query", options=options)
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
