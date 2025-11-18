"""Regression tests for the thin semantic adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

import pytest
from codeintel_rev.errors import CatalogConsistencyError
from codeintel_rev.mcp_server.adapters import semantic as semantic_adapter
from codeintel_rev.retrieval.pipeline.stage0 import Stage0Metadata, Stage0Result

from tests._helpers import assertions


@dataclass
class _FakeCatalog(AbstractContextManager["_FakeCatalog"]):
    records: list[Mapping[str, Any]]

    def __enter__(self) -> _FakeCatalog:  # pragma: no cover - trivial
        return self

    def __exit__(self, *exc: object) -> bool:  # pragma: no cover - trivial
        return False

    def query_by_ids(self, chunk_ids: Sequence[int]) -> list[Mapping[str, Any]]:
        return [record for record in self.records if record["id"] in chunk_ids]

    def query_by_filters(self, chunk_ids: Sequence[int], **_: object) -> list[Mapping[str, Any]]:
        return self.query_by_ids(chunk_ids)

    def get_structure_annotations(self, ids: Sequence[int]) -> Mapping[int, Any]:
        return {int(chunk_id): None for chunk_id in ids}


@dataclass
class _FakeContext:
    catalog: _FakeCatalog

    def __post_init__(self) -> None:
        self.settings = type(
            "Settings",
            (),
            {"index": type("Idx", (), {"rrf_k": 60})},
        )()

    def open_catalog(self) -> _FakeCatalog:
        return self.catalog


def _stage0_result() -> Stage0Result:
    return Stage0Result(
        ids=[1],
        scores=[0.9],
        warnings=["fanout:limited"],
        method={"retrieval": ["semantic"]},
        channels=["semantic"],
        contributions={1: [("semantic", 1, 0.9)]},
    )


def _stage0_metadata() -> Stage0Metadata:
    return Stage0Metadata(limits=["limit:clamped"], effective_limit=5, requested_limit=5)


def test_semantic_search_sync_returns_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    """semantic_search hydrates catalog rows and propagates limits metadata."""
    context = _FakeContext(
        catalog=_FakeCatalog(
            records=[
                {"id": 1, "uri": "src/file.py", "start_line": 1, "end_line": 2, "preview": "code"}
            ]
        ),
    )

    monkeypatch.setattr(
        semantic_adapter,
        "execute_semantic_stage0",
        lambda _request: (_stage0_result(), _stage0_metadata()),
    )

    envelope = semantic_adapter._semantic_search_sync(
        context=context,
        query="vector",
        limit=5,
        scope=None,
    )

    assertions.expect_true(envelope["findings"])
    assertions.expect_equal(envelope["findings"][0]["chunk_id"], 1)
    assertions.expect_in("Hybrid RRF", envelope["findings"][0]["why"])
    assertions.expect_equal(envelope["limits"], ["limit:clamped"])


def test_semantic_search_sync_raises_on_hydration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hydration failures bubble up as CatalogConsistencyError."""
    context = _FakeContext(catalog=_FakeCatalog(records=[]))

    def _failing_hydrate(*_: object, **__: object) -> tuple[list[dict], Exception]:
        return [], RuntimeError("boom")

    monkeypatch.setattr(
        semantic_adapter,
        "execute_semantic_stage0",
        lambda _request: (_stage0_result(), _stage0_metadata()),
    )
    monkeypatch.setattr(semantic_adapter, "_hydrate_findings", _failing_hydrate)

    with pytest.raises(CatalogConsistencyError):
        semantic_adapter._semantic_search_sync(context=context, query="test", limit=5, scope=None)


@pytest.mark.asyncio
async def test_semantic_search_async_invokes_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """Public async API delegates to the sync helper."""
    context = _FakeContext(
        catalog=_FakeCatalog(
            records=[
                {
                    "id": 1,
                    "uri": "src/file.py",
                    "start_line": 0,
                    "end_line": 1,
                    "preview": "snippet",
                }
            ]
        ),
    )

    async def _fake_scope(*_: object, **__: object) -> None:
        return None

    monkeypatch.setattr(semantic_adapter, "get_effective_scope", _fake_scope)
    monkeypatch.setattr(
        semantic_adapter,
        "execute_semantic_stage0",
        lambda _request: (_stage0_result(), _stage0_metadata()),
    )
    monkeypatch.setattr(semantic_adapter, "get_session_id", lambda: "session-1")

    envelope = await semantic_adapter.semantic_search(context, "query", limit=5)
    assertions.expect_equal(envelope["findings"][0]["chunk_id"], 1)
