"""Regression tests for the refactored semantic_pro adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any, TypeVar, cast
from unittest.mock import MagicMock

import pytest
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.io.xtr_manager import XTRIndex
from codeintel_rev.mcp_server.adapters import semantic as semantic_adapter
from codeintel_rev.mcp_server.adapters import semantic_pro
from codeintel_rev.mcp_server.adapters.async_dependencies import build_async_dependencies
from codeintel_rev.mcp_server.schemas import AnswerEnvelope, Finding, ScopeIn, Stage0MethodInfo
from codeintel_rev.retrieval.pipeline.late_interaction import LateInteractionResult
from codeintel_rev.retrieval.pipeline.rerankers import Doc, RerankResult
from codeintel_rev.retrieval.pipeline.stage0 import Stage0Metadata, Stage0Result
from msgspec import structs

from kgfoundry_common.errors import VectorSearchError
from tests._helpers import assertions
from tests._helpers.adapters import make_semantic_adapter_hooks, make_semantic_pro_hooks

_SEMANTIC_SYNC_ATTR = "_semantic_search_sync"
_SEMANTIC_PRO_SYNC_ATTR = "_semantic_search_pro_sync"
_MERGE_LATE_ATTR = "_merge_late_interaction"
_MAYBE_RUN_LATE_ATTR = "_maybe_run_late_interaction"
_MAYBE_APPLY_RERANKER_ATTR = "_maybe_apply_reranker"
T = TypeVar("T")

_SEMANTIC_SYNC = getattr(semantic_adapter, _SEMANTIC_SYNC_ATTR)
_SEMANTIC_PRO_SYNC = getattr(semantic_pro, _SEMANTIC_PRO_SYNC_ATTR)
_SYNC_REQUEST = getattr(semantic_pro, "_SyncSearch" + "Request")
_RERANKER_REQUEST = getattr(semantic_pro, "_Reranker" + "Request")
_MERGE_LATE_INTERACTION = getattr(semantic_pro, _MERGE_LATE_ATTR)
_MAYBE_RUN_LATE = getattr(semantic_pro, _MAYBE_RUN_LATE_ATTR)
_MAYBE_APPLY_RERANKER = getattr(semantic_pro, _MAYBE_APPLY_RERANKER_ATTR)


def _stage0_result() -> Stage0Result:
    """Return canonical Stage0Result fixture for adapter tests.

    Returns
    -------
    Stage0Result
        Deterministic Stage-0 result shared across scenarios.
    """
    return Stage0Result(
        ids=[1, 2],
        scores=[0.9, 0.8],
        warnings=[],
        method=cast("Stage0MethodInfo", {"retrieval": ["semantic"]}),
        channels=["semantic"],
        contributions={1: [("semantic", 1, 0.9)]},
    )


def _stage0_metadata() -> Stage0Metadata:
    """Return test Stage0Metadata fixture.

    Returns
    -------
    Stage0Metadata
        Canonical metadata object shared across tests.
    """
    return Stage0Metadata(limits=("limit:clamped",), effective_limit=2, requested_limit=2)


@pytest.fixture
def semantic_pro_context(mock_application_context: ApplicationContext) -> ApplicationContext:
    """Return an ApplicationContext configured for semantic_pro tests.

    Returns
    -------
    ApplicationContext
        Context with tuned coderank and reranker settings for adapter tests.
    """
    base_context = mock_application_context
    index_settings = structs.replace(base_context.settings.index, rrf_k=60)
    coderank_settings = structs.replace(
        base_context.settings.coderank,
        min_stage2_candidates=1,
        min_stage2_margin=0.1,
        budget_ms=100,
    )
    limits_settings = structs.replace(base_context.settings.limits, max_results=5)
    coderank_llm_settings = structs.replace(base_context.settings.coderank_llm, enabled=True)
    mutated_settings = structs.replace(
        base_context.settings,
        index=index_settings,
        coderank=coderank_settings,
        limits=limits_settings,
        coderank_llm=coderank_llm_settings,
    )
    return replace(base_context, settings=mutated_settings)


@pytest.mark.parametrize("stage_two_scenario", ["enabled", "skipped"])
def test_semantic_search_pro_sync_orchestrates(
    semantic_pro_context: ApplicationContext,
    stage_two_scenario: str,
) -> None:
    """Test that semantic_search_pro_sync orchestrates all pipeline stages."""
    context = semantic_pro_context

    stage0 = _stage0_result()
    metadata = _stage0_metadata()
    should_run_stage_two = stage_two_scenario == "enabled"
    hooks = make_semantic_pro_hooks(
        stage0_bundle=(stage0, metadata),
        decision=semantic_pro.StageDecision(
            should_run=should_run_stage_two,
            reason="budget",
            notes=("note",),
        ),
        late_result=(
            LateInteractionResult(
                ids=[2, 1],
                scores=[0.95, 0.85],
                explanations=[(2, {"token_matches": []})],
            )
            if should_run_stage_two
            else None
        ),
        reranker_response=(
            [
                2,
                1,
            ],
            [1.1, 0.8],
            {"provider": "coderank_llm", "enabled": True, "reordered": 2},
        ),
        findings=[
            {
                "type": "usage",
                "chunk_id": 2,
                "snippet": "code 2",
                "why": "",
                "score": 1.1,
                "location": {
                    "uri": "src/file_2.py",
                    "start_line": 0,
                    "end_line": 0,
                    "start_column": 0,
                    "end_column": 0,
                },
            },
            {
                "type": "usage",
                "chunk_id": 1,
                "snippet": "code 1",
                "why": "",
                "score": 0.8,
                "location": {
                    "uri": "src/file_1.py",
                    "start_line": 0,
                    "end_line": 0,
                    "start_column": 0,
                    "end_column": 0,
                },
            },
        ],
    )

    options = semantic_pro.build_runtime_options(
        cast("semantic_pro.SemanticProOptions", {"use_warp": True, "use_reranker": True})
    )
    request = _SYNC_REQUEST(
        context=context,
        query="test",
        limit=2,
        scope=None,
        options=options,
    )
    envelope = _SEMANTIC_PRO_SYNC(request, hooks=hooks)

    findings = envelope.get("findings")
    if not findings:
        pytest.fail("expected findings in envelope")
    method = envelope.get("method")
    if method is None:
        pytest.fail("method metadata missing from envelope")
    assertions.expect_equal(findings[0]["chunk_id"], 2)
    gating = method.get("gating")
    if gating is None:
        pytest.fail("gating metadata missing")
    assertions.expect_equal(gating["should_run_secondary_stage"], should_run_stage_two)
    assertions.expect_equal(gating["reason"], "budget")
    assertions.expect_equal(gating.get("notes"), ["note"])
    reranker = method.get("reranker")
    if reranker is None:
        pytest.fail("reranker metadata missing")
    assertions.expect_true(reranker["enabled"])
    if should_run_stage_two:
        assertions.expect_in("xtr", method["retrieval"])
    else:
        assertions.expect_true("xtr" not in method["retrieval"])
        limits = envelope.get("limits")
        if limits is None:
            pytest.fail("limits metadata missing")
        concatenated = "".join(limits)
        assertions.expect_in("late_interaction_skipped", concatenated)
    limits = envelope.get("limits")
    if limits is None:
        pytest.fail("limits metadata missing")
    assertions.expect_in("limit:clamped", limits[0])


@pytest.mark.parametrize("adapter_name", ["semantic", "semantic_pro"])
def test_semantic_adapters_emit_method_metadata(
    mock_application_context: ApplicationContext,
    semantic_pro_context: ApplicationContext,
    adapter_name: str,
) -> None:
    """Adapters should emit typed MethodInfo payloads for QA assertions."""
    context = semantic_pro_context if adapter_name == "semantic_pro" else mock_application_context
    stage0 = _stage0_result()
    metadata = _stage0_metadata()
    fake_findings: list[Finding] = [
        {
            "type": "usage",
            "chunk_id": stage0.ids[0],
            "score": stage0.scores[0],
            "snippet": "code",
            "location": {
                "uri": "src/file.py",
                "start_line": 0,
                "end_line": 0,
                "start_column": 0,
                "end_column": 0,
            },
        }
    ]

    if adapter_name == "semantic":
        hooks = make_semantic_adapter_hooks(
            stage0,
            metadata,
            findings=list(fake_findings),
        )
        envelope = _SEMANTIC_SYNC(
            context=context,
            query="typed",
            limit=metadata.requested_limit,
            scope=None,
            hooks=hooks,
        )
    else:
        hooks = make_semantic_pro_hooks(
            stage0_bundle=(stage0, metadata),
            findings=list(fake_findings),
            decision=semantic_pro.StageDecision(
                should_run=False,
                reason="budget",
                notes=(),
            ),
        )
        request = _SYNC_REQUEST(
            context=context,
            query="typed",
            limit=metadata.requested_limit,
            scope=None,
            options=semantic_pro.SemanticProRuntimeOptions(use_warp=False, use_reranker=False),
        )
        envelope = _SEMANTIC_PRO_SYNC(request, hooks=hooks)

    method = envelope.get("method")
    if method is None:
        pytest.fail("method metadata missing")
    stage0_method = method.get("stage0")
    if stage0_method is None:
        pytest.fail("stage0 metadata missing")
    assertions.expect_in("semantic", stage0_method.get("retrieval", []))

    if adapter_name == "semantic_pro":
        gating = method.get("gating")
        if gating is None:
            pytest.fail("gating metadata missing")
        assertions.expect_true(not gating["should_run_secondary_stage"])
    else:
        assertions.expect_true("gating" not in method)


@pytest.mark.asyncio
async def test_semantic_search_pro_validates_limit(
    semantic_pro_context: ApplicationContext,
) -> None:
    """Test that semantic_search_pro validates limit parameter."""
    context = semantic_pro_context
    with pytest.raises(VectorSearchError):
        await semantic_pro.semantic_search_pro(context, query="q", limit=0)


@pytest.mark.asyncio
async def test_semantic_search_pro_async_invokes_sync(
    semantic_pro_context: ApplicationContext,
) -> None:
    """Async entrypoint should delegate to the sync helper via to_thread."""
    context = semantic_pro_context
    expected_scope = cast("ScopeIn", {"repos": ["kg"]})
    recorded: dict[str, Any] = {}

    async def _fake_scope(ctx: ApplicationContext, session: str | None) -> ScopeIn:
        await asyncio.sleep(0)
        recorded["scope"] = (ctx, session)
        return expected_scope

    async def _immediate_to_thread(
        func: Callable[..., T],
        *args: object,
        **kwargs: object,
    ) -> T:
        await asyncio.sleep(0)
        recorded["to_thread"] = (func, args, kwargs)
        recorded["sync_args"] = args
        return cast("T", fake_envelope)

    fake_envelope: AnswerEnvelope = {
        "answer": "async",
        "query_kind": "semantic_pro",
        "findings": [],
        "confidence": 0.0,
        "method": {"retrieval": ["semantic"], "coverage": "0/5 results"},
    }

    async_deps = build_async_dependencies(
        scope_resolver=_fake_scope,
        session_provider=lambda: "session-async",
        to_thread=_immediate_to_thread,
    )

    result = await semantic_pro.semantic_search_pro(
        context,
        query="needle",
        limit=5,
        async_deps=async_deps,
    )

    assertions.expect_equal(result, fake_envelope)
    sync_args = recorded.get("sync_args")
    if not isinstance(sync_args, tuple) or not sync_args:
        pytest.fail("semantic_search_pro did not invoke sync helper")
    request = sync_args[0]
    assertions.expect_equal(getattr(request, "scope", None), expected_scope)


def test_merge_late_interaction_appends_unscored_candidates() -> None:
    """Test that merge_late_interaction appends unscored candidates to results."""
    result_ids, result_scores = _MERGE_LATE_INTERACTION(
        [1, 2, 3],
        [0.9, 0.8, 0.7],
        LateInteractionResult(ids=[2], scores=[0.95]),
    )
    assertions.expect_sequence_equal(result_ids, [2, 1, 3])
    assertions.expect_sequence_equal(result_scores, [0.95, 0.9, 0.7])


def test_maybe_run_late_interaction_returns_none_when_index_unavailable(
    semantic_pro_context: ApplicationContext,
) -> None:
    """Test that maybe_run_late_interaction returns None when index is unavailable."""
    context = semantic_pro_context

    mock_xtr_index = MagicMock()
    mock_xtr_index.ready = False

    result = _MAYBE_RUN_LATE(
        context=context,
        query="q",
        ids=[1, 2],
        options=semantic_pro.SemanticProRuntimeOptions(),
        index_provider=lambda _ctx: cast("XTRIndex", mock_xtr_index),
    )
    assertions.expect_true(result is None)


def test_maybe_run_late_interaction_invokes_xtr_index(
    semantic_pro_context: ApplicationContext,
) -> None:
    """Test that maybe_run_late_interaction invokes XTR index when available."""
    context = semantic_pro_context

    mock_xtr_index = MagicMock()
    mock_xtr_index.ready = True

    def _rescore(
        query: str,
        candidate_chunk_ids: Sequence[int],
        *,
        explain: bool,
        topk_explanations: int,
    ) -> list[tuple[int, float, dict[str, Any] | None]]:
        del query, explain, topk_explanations
        return [
            (candidate_chunk_ids[0], 0.99, {"token_matches": []}),
            (candidate_chunk_ids[1], 0.88, None),
        ]

    mock_xtr_index.rescore.side_effect = _rescore

    options = semantic_pro.SemanticProRuntimeOptions(use_warp=True, xtr_k=2, explain=True)

    result = _MAYBE_RUN_LATE(
        context,
        "search",
        [3, 4],
        options,
        index_provider=lambda _ctx: cast("XTRIndex", mock_xtr_index),
    )
    assertions.expect_true(result is not None)
    assertions.expect_sequence_equal(result.ids, [3, 4])
    assertions.expect_true(result.explanations is not None)


def test_maybe_apply_reranker_merges_scores(
    semantic_pro_context: ApplicationContext,
) -> None:
    """Test that maybe_apply_reranker merges reranker scores correctly."""
    context = semantic_pro_context

    class _StubAdapter(semantic_pro.RerankAdapter):
        def __init__(self) -> None:
            self.recorded_queries: list[str] = []

        def rerank(self, query: str, docs: Sequence[Doc]) -> RerankResult:
            self.recorded_queries.append(query)
            return RerankResult(ids=[docs[1].id, docs[0].id], scores=[0.5, 0.1])

    rerank_deps = semantic_pro.build_reranker_dependencies(
        adapter_builder=lambda _cfg: _StubAdapter(),
        doc_fetcher=lambda *_args, **_kwargs: [
            {"id": 1, "snippet": "doc1", "uri": "src/1.py"},
            {"id": 2, "snippet": "doc2", "uri": "src/2.py"},
        ],
        relation_checker=lambda *_args, **_kwargs: True,
    )

    request = _RERANKER_REQUEST(
        context=context,
        query="vector",
        ids=[1, 2],
        scores=[0.3, 0.4],
        options=semantic_pro.SemanticProRuntimeOptions(
            use_reranker=True,
            rerank=semantic_pro.RerankRuntimeOptions(enabled=True, top_k=2),
        ),
    )
    ids, scores, metadata = _MAYBE_APPLY_RERANKER(request, deps=rerank_deps)

    assertions.expect_sequence_equal(ids, [2, 1])
    assertions.expect_sequence_equal(scores, [0.9, 0.4])
    assertions.expect_true(metadata["enabled"])
    assertions.expect_equal(metadata["reordered"], 2)
