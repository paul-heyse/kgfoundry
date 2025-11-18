"""Shared adapter fixtures for semantic and semantic_pro tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from typing import Any, Self

from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.mcp_server.adapters import semantic as semantic_adapter
from codeintel_rev.mcp_server.adapters import semantic_pro
from codeintel_rev.mcp_server.schemas import Finding, MethodRerankerInfo, ScopeIn
from codeintel_rev.retrieval.pipeline.late_interaction import LateInteractionResult
from codeintel_rev.retrieval.pipeline.stage0 import (
    SemanticStage0Request,
    Stage0Metadata,
    Stage0Result,
)


class _CatalogStub(AbstractContextManager["_CatalogStub"]):
    """Minimal DuckDBCatalog double for unit tests."""

    def __init__(self, records: Sequence[Mapping[str, Any]]) -> None:
        self._records = [dict(record) for record in records]

    def __enter__(self) -> Self:  # pragma: no cover - trivial
        return self

    def __exit__(self, *_exc: object) -> bool:  # pragma: no cover - trivial
        return False

    def open(self) -> _CatalogStub:  # pragma: no cover - parity with DuckDBCatalog
        return self

    def close(self) -> None:  # pragma: no cover - trivial
        del self

    def connection(self) -> _CatalogStub:  # pragma: no cover - tests do not use
        return self

    def query_by_ids(self, chunk_ids: Sequence[int]) -> list[Mapping[str, Any]]:
        return [record for record in self._records if record.get("id") in chunk_ids]

    def query_by_filters(
        self, chunk_ids: Sequence[int], **_: object
    ) -> list[Mapping[str, Any]]:
        return self.query_by_ids(chunk_ids)

    @staticmethod
    def get_structure_annotations(ids: Sequence[int]) -> Mapping[int, Any]:
        return {int(chunk_id): None for chunk_id in ids}


def context_with_catalog_records(
    context: ApplicationContext,
    records: Sequence[Mapping[str, Any]],
) -> ApplicationContext:
    """Return a context whose catalog factory yields the provided records.

    Returns
    -------
    ApplicationContext
        New context instance whose ``open_catalog`` method surfaces the
        synthetic records.
    """

    def _factory(*_args: object, **_kwargs: object) -> _CatalogStub:
        return _CatalogStub(records)

    return context.with_overrides(duckdb_catalog_factory=_factory)


def make_semantic_adapter_hooks(
    stage0_result: Stage0Result,
    metadata: Stage0Metadata,
    *,
    findings: list[Finding] | None = None,
    hydration_error: Exception | None = None,
) -> semantic_adapter.SemanticAdapterHooks:
    """Build semantic adapter hooks for deterministic hydration tests.

    Returns
    -------
    SemanticAdapterHooks
        Hooks configured with deterministic Stage-0 execution and hydration.
    """

    def _execute_stage0(_request: SemanticStage0Request) -> tuple[
        Stage0Result,
        Stage0Metadata,
    ]:
        del _request
        return stage0_result, metadata

    if findings is None and hydration_error is None:
        hydrate = getattr(semantic_adapter, "_hydrate_" + "findings")
    else:
        def _hydrate(
            ctx: ApplicationContext,
            chunk_ids: Sequence[int],
            scores: Sequence[float],
            scope: ScopeIn | None,
        ) -> tuple[list[Finding], Exception | None]:
            del ctx, chunk_ids, scores, scope
            hydrated = list(findings) if findings is not None else []
            return hydrated, hydration_error

        hydrate = _hydrate

    return semantic_adapter.build_semantic_adapter_hooks(
        execute_stage0=_execute_stage0,
        hydrate_findings=hydrate,
    )


def make_semantic_pro_hooks(
    stage0_bundle: tuple[Stage0Result, Stage0Metadata],
    *,
    decision: semantic_pro.StageDecision | None = None,
    late_result: LateInteractionResult | None = None,
    reranker_response: tuple[list[int], list[float], MethodRerankerInfo] | None = None,
    findings: list[Finding] | None = None,
) -> semantic_pro.SemanticProHooks:
    """Return semantic_pro hooks wired to canned fixtures.

    Returns
    -------
    SemanticProHooks
        Fully populated hook bundle suitable for deterministic adapter tests.
    """
    stage0_result, metadata = stage0_bundle

    def _exec(_request: SemanticStage0Request) -> tuple[Stage0Result, Stage0Metadata]:
        del _request
        return stage0_result, metadata

    def _decide(
        ctx: ApplicationContext,
        ids: Sequence[int],
        scores: Sequence[float],
    ) -> semantic_pro.StageDecision:
        del ctx, ids, scores
        return decision or semantic_pro.StageDecision(
            should_run=False,
            reason="tests",
            notes=(),
        )

    def _late(
        ctx: ApplicationContext,
        query: str,
        ids: Sequence[int],
        options: semantic_pro.SemanticProRuntimeOptions,
    ) -> LateInteractionResult | None:
        del ctx, query, ids, options
        return late_result

    def _rerank(
        request: object,
        deps: semantic_pro.RerankerDependencies | None,
    ) -> tuple[list[int], list[float], MethodRerankerInfo]:
        del request, deps
        default_metadata: MethodRerankerInfo = {
            "provider": "coderank_llm",
            "enabled": False,
            "reason": "tests",
        }
        return reranker_response or (
            list(stage0_result.ids),
            list(stage0_result.scores),
            default_metadata,
        )

    def _hydrate(
        ctx: ApplicationContext,
        chunk_ids: Sequence[int],
        scores: Sequence[float],
        scope: ScopeIn | None,
    ) -> list[Finding]:
        del ctx, chunk_ids, scores, scope
        return list(findings) if findings is not None else []

    return semantic_pro.build_semantic_pro_hooks(
        execute_stage0=_exec,
        decide_stage_two=_decide,
        run_late_interaction=_late,
        apply_reranker=_rerank,
        hydrate_findings=_hydrate,
    )


__all__ = [
    "context_with_catalog_records",
    "make_semantic_adapter_hooks",
    "make_semantic_pro_hooks",
]
