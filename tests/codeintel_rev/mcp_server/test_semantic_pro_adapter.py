"""Regression tests for the refactored semantic_pro adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol

import pytest
from codeintel_rev.mcp_server.adapters import semantic_pro
from codeintel_rev.retrieval.pipeline.late_interaction import LateInteractionResult
from codeintel_rev.retrieval.pipeline.rerankers import RerankResult
from codeintel_rev.retrieval.pipeline.stage0 import Stage0Metadata, Stage0Result

from kgfoundry_common.errors import VectorSearchError
from tests._helpers import assertions


class _MockConnection(Protocol):
    """Protocol for mock DuckDB connection in tests."""

    def __enter__(self) -> _MockConnection:
        """Enter context manager."""
        ...

    def __exit__(self, *exc: object) -> bool:
        """Exit context manager."""
        ...

    def execute(self, _query: str, params: tuple[Sequence[int]]) -> _MockResult:
        """Execute a query."""
        ...


class _MockResult(Protocol):
    """Protocol for mock DuckDB query result in tests."""

    def fetchone(self) -> tuple[int, str, str] | None:
        """Fetch one row."""
        ...

    def fetchall(self) -> list[tuple[int, str, str]]:
        """Fetch all rows."""
        ...


@dataclass
class _FakeContext:
    def __post_init__(self) -> None:
        self.settings = type(
            "Settings",
            (),
            {
                "index": type("Idx", (), {"rrf_k": 60}),
                "coderank": type(
                    "Coderank",
                    (),
                    {"min_stage2_candidates": 1, "min_stage2_margin": 0.1, "budget_ms": 100},
                ),
                "limits": type("Limits", (), {"max_results": 5}),
                "xtr": type("XTR", (), {"enable": True, "candidate_k": 5}),
                "coderank_llm": type(
                    "CoderankLLM",
                    (),
                    {
                        "enabled": True,
                        "model_id": "stub",
                        "device": "cpu",
                        "max_new_tokens": 64,
                        "temperature": 0.0,
                        "top_p": 0.95,
                    },
                ),
            },
        )()

    def open_catalog(self) -> _CatalogCtx:
        return _CatalogCtx()


class _CatalogCtx:
    def __enter__(self) -> _CatalogCtx:  # pragma: no cover - trivial
        return self

    def __exit__(self, *exc: object) -> bool:  # pragma: no cover - trivial
        return False

    def query_by_ids(self, chunk_ids: list[int]) -> list[Mapping[str, Any]]:
        return [
            {
                "id": chunk_id,
                "uri": f"src/file_{chunk_id}.py",
                "start_line": 1,
                "end_line": 2,
                "preview": f"code {chunk_id}",
            }
            for chunk_id in chunk_ids
        ]

    def query_by_filters(self, chunk_ids: list[int], **_: object) -> list[Mapping[str, Any]]:
        return self.query_by_ids(chunk_ids)

    def get_structure_annotations(self, ids: list[int]) -> Mapping[int, Any]:
        return dict.fromkeys(ids)

    def connection(self) -> AbstractContextManager[_MockConnection]:
        class _Conn:
            def __enter__(self) -> _Conn:
                return self

            def __exit__(self, *exc: object) -> bool:
                return False

            def execute(self, _query: str, params: tuple[Sequence[int]]) -> _Result:
                chunk_ids = params[0] if isinstance(params, (list, tuple)) else params
                if isinstance(chunk_ids, int):
                    chunk_ids = [chunk_ids]

                class _Result:
                    def __init__(self, rows: list[tuple[int, str, str]]) -> None:
                        self._rows = rows

                    def fetchone(self) -> tuple[int, str, str] | None:
                        return self._rows[0] if self._rows else None

                    def fetchall(self) -> list[tuple[int, str, str]]:
                        return list(self._rows)

                rows = [
                    (chunk_id, f"snippet {chunk_id}", f"src/{chunk_id}.py")
                    for chunk_id in chunk_ids
                ]
                return _Result(rows)

        class _ConnContextManager:
            def __enter__(self) -> _Conn:
                return _Conn()

            def __exit__(self, *exc: object) -> bool:
                return False

        return _ConnContextManager()


def _stage0_result() -> Stage0Result:
    return Stage0Result(
        ids=[1, 2],
        scores=[0.9, 0.8],
        warnings=[],
        method={"retrieval": ["semantic"]},
        channels=["semantic"],
        contributions={1: [("semantic", 1, 0.9)]},
    )


def _stage0_metadata() -> Stage0Metadata:
    """Return test Stage0Metadata fixture."""
    return Stage0Metadata(limits=["limit:clamped"], effective_limit=2, requested_limit=2)


def test_semantic_search_pro_sync_orchestrates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that semantic_search_pro_sync orchestrates all pipeline stages."""
    context = _FakeContext()

    monkeypatch.setattr(
        semantic_pro,
        "execute_semantic_stage0",
        lambda _request: (_stage0_result(), _stage0_metadata()),
    )
    monkeypatch.setattr(
        semantic_pro,
        "_maybe_run_late_interaction",
        lambda *_args, **_kwargs: LateInteractionResult(
            ids=[2, 1], scores=[0.95, 0.85], explanations=[(2, {"token_matches": []})]
        ),
    )
    monkeypatch.setattr(
        semantic_pro,
        "_maybe_apply_reranker",
        lambda *_args, **_kwargs: ([2, 1], [1.1, 0.8], {"enabled": True}),
    )
    monkeypatch.setattr(
        semantic_pro,
        "_hydrate_findings",
        lambda *_args, **_kwargs: [
            {
                "chunk_id": 2,
                "uri": "src/file_2.py",
                "snippet": "code 2",
                "why": "",
                "score": 1.1,
                "location": {
                    "uri": "",
                    "start_line": 0,
                    "end_line": 0,
                    "start_column": 0,
                    "end_column": 0,
                },
            },
            {
                "chunk_id": 1,
                "uri": "src/file_1.py",
                "snippet": "code 1",
                "why": "",
                "score": 0.8,
                "location": {
                    "uri": "",
                    "start_line": 0,
                    "end_line": 0,
                    "start_column": 0,
                    "end_column": 0,
                },
            },
        ],
    )

    envelope = semantic_pro._semantic_search_pro_sync(
        context=context,
        query="test",
        limit=2,
        scope=None,
        options=semantic_pro.build_runtime_options({"use_warp": True, "use_reranker": True}),
    )

    assertions.expect_equal(envelope["findings"][0]["chunk_id"], 2)
    assertions.expect_true(envelope["method"]["gating"]["should_run_secondary_stage"])
    assertions.expect_true(envelope["method"]["reranker"]["enabled"])
    assertions.expect_in("limit:clamped", envelope["limits"])


@pytest.mark.asyncio
async def test_semantic_search_pro_validates_limit() -> None:
    """Test that semantic_search_pro validates limit parameter."""
    context = _FakeContext()
    with pytest.raises(VectorSearchError):
        await semantic_pro.semantic_search_pro(context, query="q", limit=0)


def test_merge_late_interaction_appends_unscored_candidates() -> None:
    """Test that merge_late_interaction appends unscored candidates to results."""
    result_ids, result_scores = semantic_pro._merge_late_interaction(
        [1, 2, 3],
        [0.9, 0.8, 0.7],
        LateInteractionResult(ids=[2], scores=[0.95]),
    )
    assertions.expect_sequence_equal(result_ids, [2, 1, 3])
    assertions.expect_sequence_equal(result_scores, [0.95, 0.9, 0.7])


def test_maybe_run_late_interaction_returns_none_when_index_unavailable() -> None:
    """Test that maybe_run_late_interaction returns None when index is unavailable."""
    context = _FakeContext()

    class _Index:
        ready = False

    context.get_xtr_index = lambda: _Index()
    result = semantic_pro._maybe_run_late_interaction(
        context=context,
        query="q",
        ids=[1, 2],
        options=semantic_pro.SemanticProRuntimeOptions(),
    )
    assertions.expect_true(result is None)


def test_maybe_run_late_interaction_invokes_xtr_index() -> None:
    """Test that maybe_run_late_interaction invokes XTR index when available."""
    context = _FakeContext()

    class _Index:
        ready = True

        def rescore(
            self,
            _query: str,
            candidate_chunk_ids: Sequence[int],
            *,
            _explain: bool,
            _topk_explanations: int,
        ) -> list[tuple[int, float, dict[str, Any] | None]]:
            return [
                (candidate_chunk_ids[0], 0.99, {"token_matches": []}),
                (candidate_chunk_ids[1], 0.88, None),
            ]

    context.get_xtr_index = lambda: _Index()
    options = semantic_pro.SemanticProRuntimeOptions(use_warp=True, xtr_k=2, explain=True)

    result = semantic_pro._maybe_run_late_interaction(context, "search", [3, 4], options)
    assert result is not None
    assertions.expect_sequence_equal(result.ids, [3, 4])
    assertions.expect_true(result.explanations is not None)


def test_maybe_apply_reranker_merges_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that maybe_apply_reranker merges reranker scores correctly."""
    context = _FakeContext()

    class _StubAdapter:
        def rerank(self, _query: str, docs: list[semantic_pro.Doc]) -> RerankResult:
            return RerankResult(ids=[docs[1].id, docs[0].id], scores=[0.5, 0.1])

    monkeypatch.setattr(semantic_pro, "_build_coderank_adapter", lambda _cfg: _StubAdapter())
    monkeypatch.setattr(semantic_pro, "relation_exists", lambda *_: True)
    monkeypatch.setattr(
        semantic_pro,
        "_fetch_docs_for_reranker",
        lambda *_args, **_kwargs: [
            {"id": 1, "snippet": "doc1", "uri": "src/1.py"},
            {"id": 2, "snippet": "doc2", "uri": "src/2.py"},
        ],
    )

    ids, scores, metadata = semantic_pro._maybe_apply_reranker(
        context=context,
        query="vector",
        ids=[1, 2],
        scores=[0.3, 0.4],
        options=semantic_pro.SemanticProRuntimeOptions(
            use_reranker=True,
            rerank=semantic_pro.RerankRuntimeOptions(enabled=True, top_k=2),
        ),
    )

    assertions.expect_sequence_equal(ids, [2, 1])
    assertions.expect_sequence_equal(scores, [0.9, 0.4])
    assertions.expect_true(metadata["enabled"])
    assertions.expect_equal(metadata["reordered"], 2)
