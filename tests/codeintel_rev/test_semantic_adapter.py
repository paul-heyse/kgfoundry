"""Regression tests for the thin semantic adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, cast

import pytest
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.errors import CatalogConsistencyError
from codeintel_rev.mcp_server.adapters import semantic as semantic_adapter
from codeintel_rev.mcp_server.adapters.async_dependencies import build_async_dependencies
from codeintel_rev.mcp_server.schemas import AnswerEnvelope, ScopeIn, Stage0MethodInfo
from codeintel_rev.retrieval.pipeline.stage0 import Stage0Metadata, Stage0Result

from tests._helpers import assertions
from tests._helpers.adapters import (
    context_with_catalog_records,
    make_semantic_adapter_hooks,
)

_SEMANTIC_SYNC_ATTR = "_semantic_search_sync"
_SEMANTIC_SYNC = getattr(semantic_adapter, _SEMANTIC_SYNC_ATTR)


def _stage0_result() -> Stage0Result:
    return Stage0Result(
        ids=[1],
        scores=[0.9],
        warnings=["fanout:limited"],
        method=cast("Stage0MethodInfo", {"retrieval": ["semantic"]}),
        channels=["semantic"],
        contributions={1: [("semantic", 1, 0.9)]},
    )


def _stage0_metadata() -> Stage0Metadata:
    return Stage0Metadata(limits=("limit:clamped",), effective_limit=5, requested_limit=5)


def test_semantic_search_sync_returns_findings(
    mock_application_context: ApplicationContext,
) -> None:
    """semantic_search hydrates catalog rows and propagates limits metadata."""
    context = context_with_catalog_records(
        mock_application_context,
        records=[
            {
                "id": 1,
                "uri": "src/file.py",
                "start_line": 1,
                "end_line": 2,
                "preview": "code",
            }
        ],
    )
    hooks = make_semantic_adapter_hooks(_stage0_result(), _stage0_metadata())

    envelope = _SEMANTIC_SYNC(
        context=context,
        query="vector",
        limit=5,
        scope=None,
        hooks=hooks,
    )

    findings = envelope.get("findings")
    if not findings:
        pytest.fail("expected findings in envelope")
    chunk_id = findings[0].get("chunk_id")
    if chunk_id is None:
        pytest.fail("expected chunk_id field on finding")
    assertions.expect_equal(chunk_id, 1)
    assertions.expect_in("Hybrid RRF", findings[0]["why"])
    limits = envelope.get("limits")
    if limits is None:
        pytest.fail("expected limits metadata")
    assertions.expect_equal(limits, ["limit:clamped"])


def test_semantic_search_sync_raises_on_hydration_error(
    mock_application_context: ApplicationContext,
) -> None:
    """Hydration failures bubble up as CatalogConsistencyError."""
    context = mock_application_context

    def _failing_hydrate(*_: object, **__: object) -> tuple[list[dict], Exception]:
        return [], RuntimeError("boom")

    hooks = make_semantic_adapter_hooks(
        _stage0_result(),
        _stage0_metadata(),
        findings=[],
        hydration_error=RuntimeError("boom"),
    )

    with pytest.raises(CatalogConsistencyError):
        _SEMANTIC_SYNC(context=context, query="test", limit=5, scope=None, hooks=hooks)


@pytest.mark.asyncio
async def test_semantic_search_async_invokes_sync(
    mock_application_context: ApplicationContext,
) -> None:
    """Public async API delegates to the sync helper."""
    context = context_with_catalog_records(
        mock_application_context,
        records=[
            {
                "id": 1,
                "uri": "src/file.py",
                "start_line": 0,
                "end_line": 1,
                "preview": "snippet",
            }
        ],
    )
    hooks = make_semantic_adapter_hooks(_stage0_result(), _stage0_metadata())

    async def _fake_scope(*_: object, **__: object) -> None:
        await asyncio.sleep(0)

    async_deps = build_async_dependencies(
        scope_resolver=_fake_scope,
        session_provider=lambda: "session-1",
    )

    envelope = await semantic_adapter.semantic_search(
        context,
        "query",
        limit=5,
        async_deps=async_deps,
        hooks=hooks,
    )
    findings = envelope.get("findings")
    if not findings:
        pytest.fail("expected findings in envelope")
    chunk_id = findings[0].get("chunk_id")
    if chunk_id is None:
        pytest.fail("expected chunk_id field on finding")
    assertions.expect_equal(chunk_id, 1)


@pytest.mark.asyncio
async def test_semantic_search_async_delegates_to_sync(
    mock_application_context: ApplicationContext,
) -> None:
    """semantic_search runs the sync helper inside asyncio.to_thread."""
    context = mock_application_context
    recorded: dict[str, Any] = {}

    async def _fake_scope(ctx: ApplicationContext, session: str | None) -> ScopeIn:
        await asyncio.sleep(0)
        recorded["scope"] = (ctx, session)
        return cast("ScopeIn", {"repos": ["kg"]})

    async def _immediate_to_thread(
        func: Callable[..., AnswerEnvelope],
        *args: object,
        **kwargs: object,
    ) -> AnswerEnvelope:
        await asyncio.sleep(0)
        recorded["to_thread"] = (func, args, kwargs)
        recorded["sync_args"] = args
        return fake_envelope

    fake_envelope: AnswerEnvelope = {
        "answer": "async",
        "query_kind": "semantic",
        "findings": [],
        "confidence": 0.0,
        "method": {"retrieval": ["semantic"], "coverage": "0/5 results"},
    }

    async_deps = build_async_dependencies(
        scope_resolver=_fake_scope,
        session_provider=lambda: "async-session",
        to_thread=_immediate_to_thread,
    )

    hooks = make_semantic_adapter_hooks(_stage0_result(), _stage0_metadata())

    result = await semantic_adapter.semantic_search(
        context,
        "async-call",
        limit=7,
        async_deps=async_deps,
        hooks=hooks,
    )

    assertions.expect_equal(result, fake_envelope)
    sync_args = recorded.get("sync_args")
    if not isinstance(sync_args, tuple):
        pytest.fail("semantic_search did not invoke sync helper")
    expected_scope = cast("ScopeIn", {"repos": ["kg"]})
    assertions.expect_equal(sync_args[3], expected_scope)
