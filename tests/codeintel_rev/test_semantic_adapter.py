"""Regression tests for the thin semantic adapter."""

from __future__ import annotations

import contextlib
from typing import cast

import pytest
from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.mcp_server.adapters import semantic as semantic_adapter
from codeintel_rev.retrieval.pipeline.gating import StageDecision
from codeintel_rev.retrieval.pipeline.stage0 import Stage0Result

from tests._helpers import assertions


class _StubContext:
    @staticmethod
    def get_hybrid_engine() -> object:  # pragma: no cover - patched run_stage0 ignores
        return object()

    @staticmethod
    def open_catalog() -> contextlib.AbstractContextManager[object]:
        return contextlib.nullcontext(object())

    runtime_cells = type("_Cells", (), {"xtr_index": object()})()  # pragma: no cover


@pytest.mark.asyncio
async def test_semantic_search_returns_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    """semantic_search hydrates catalog rows and surfaces method metadata."""
    stage0 = Stage0Result(
        ids=[1, 2], scores=[0.9, 0.8], warnings=["fanout"], method={"engine": "stub"}
    )
    monkeypatch.setattr(semantic_adapter, "run_stage0", lambda *_args, **_kwargs: stage0)
    monkeypatch.setattr(
        semantic_adapter,
        "_hydrate_findings",
        lambda *_args, **_kwargs: [{"chunk_id": 1, "score": 0.9}],
    )
    monkeypatch.setattr(
        semantic_adapter,
        "decide_secondary_stage",
        lambda *_args, **_kwargs: StageDecision(should_run=False, reason="tests"),
    )

    context = cast("ApplicationContext", _StubContext())
    envelope = await semantic_adapter.semantic_search(context, "vector", limit=5)

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
