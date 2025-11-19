"""Two-stage semantic search adapter built on the retrieval pipeline."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, relation_exists
from codeintel_rev.io.xtr_manager import XTRIndex
from codeintel_rev.mcp_server.schemas import (
    AnswerEnvelope,
    Finding,
    MethodGatingInfo,
    MethodInfo,
    MethodRerankerInfo,
    Stage0MethodInfo,
    StageInfo,
)
from codeintel_rev.retrieval.pipeline.gating import (
    StageDecision,
    StageGateConfig,
    decide_secondary_stage,
)
from codeintel_rev.retrieval.pipeline.late_interaction import (
    LateInteractionResult,
    XTRLateInteraction,
)
from codeintel_rev.retrieval.pipeline.rerankers import NoopReranker, RerankResult
from codeintel_rev.retrieval.pipeline.stage0 import Stage0Options, Stage0Result, run_stage0

if TYPE_CHECKING:
    from codeintel_rev.io.hybrid_search import HybridSearchEngine


@dataclass(frozen=True)
class SemanticProOptions:
    """User-facing options for the pro semantic adapter."""

    use_warp: bool = True
    use_reranker: bool = False
    stage_weights: Mapping[str, float] | None = None
    xtr_k: int = 50
    explain: bool = False


ProOptions = SemanticProOptions


class Stage0Runner(Protocol):
    """Protocol describing a Stage-0 hybrid search runner.

    This protocol defines the interface for executing Stage-0 hybrid retrieval,
    enabling type-safe interaction with search functionality while maintaining
    compatibility across different search implementations.
    """

    def __call__(
        self,
        engine: HybridSearchEngine,
        *,
        query: str,
        semantic_hits: Sequence[tuple[int, float]] | None,
        limit: int,
        options: Stage0Options | None = None,
    ) -> Stage0Result:
        """Execute Stage-0 hybrid search with the provided engine and query.

        Parameters
        ----------
        engine : HybridSearchEngine
            Hybrid search engine instance to use for retrieval.
        query : str
            Query text to search for.
        semantic_hits : Sequence[tuple[int, float]] | None, optional
            Optional pre-computed semantic search hits to use as input.
            If None, semantic search is performed as part of Stage-0.
        limit : int
            Maximum number of results to return.
        options : Stage0Options | None, optional
            Optional configuration for Stage-0 execution, including fusion
            weights and other search parameters. Defaults to None.

        Returns
        -------
        Stage0Result
            Result containing document IDs, scores, warnings, and method metadata
            from the Stage-0 hybrid search execution.
        """
        ...


class LateInteractionRunner(Protocol):
    """Protocol describing a late-interaction rescoring runner.

    This protocol defines the interface for executing late-interaction rescoring
    (e.g., XTR/WARP) on candidate documents, enabling type-safe interaction
    with rescoring functionality.
    """

    def rescore(
        self,
        query: str,
        candidate_ids: Sequence[int],
        *,
        explain: bool = False,
    ) -> LateInteractionResult:
        """Rescore candidate documents using late-interaction methods.

        Parameters
        ----------
        query : str
            Query text to use for rescoring.
        candidate_ids : Sequence[int]
            Sequence of document/chunk IDs to rescore.
        explain : bool, optional
            Whether to include explanation metadata in the result. Defaults to False.

        Returns
        -------
        LateInteractionResult
            Result containing rescored IDs, scores, and optional explanation
            metadata from the late-interaction execution.
        """
        ...


class Reranker(Protocol):
    """Protocol describing a reranking interface.

    This protocol defines the interface for reranking search results, enabling
    type-safe interaction with reranking functionality while maintaining
    compatibility across different reranker implementations.
    """

    def rerank(
        self,
        query: str,
        ids: Iterable[int],
        scores: Iterable[float],
    ) -> RerankResult:
        """Rerank search results using the query and initial scores.

        Parameters
        ----------
        query : str
            Query text to use for reranking.
        ids : Iterable[int]
            Iterable of document/chunk IDs to rerank.
        scores : Iterable[float]
            Iterable of initial relevance scores corresponding to each ID.

        Returns
        -------
        RerankResult
            Result containing reranked IDs and scores, potentially reordered
            and rescored based on the reranker's algorithm.
        """
        ...


StageGateDecider = Callable[[Mapping[str, object], StageGateConfig], StageDecision]
HydrateIds = Callable[[DuckDBCatalog, Sequence[int], Sequence[float]], list[Finding]]
ResolveXtrIndex = Callable[[ApplicationContext], XTRIndex | None]
LateInteractionFactory = Callable[[XTRIndex], LateInteractionRunner]
RerankerFactory = Callable[[], Reranker]


@dataclass(frozen=True, slots=True)
class SemanticProHooks:
    """Configurable collaborators for the semantic pro adapter pipeline."""

    run_stage0: Stage0Runner
    decide_secondary_stage: StageGateDecider
    hydrate_ids: HydrateIds
    resolve_xtr_index: ResolveXtrIndex
    late_interaction_factory: LateInteractionFactory
    reranker_factory: RerankerFactory

    @classmethod
    def default(cls) -> SemanticProHooks:
        """Return the production collaborators for semantic search pro.

        Returns
        -------
        SemanticProHooks
            Hook bundle referencing production implementations.
        """

        class _NoopRerankerAdapter:
            """Adapter wrapping NoopReranker to conform to Reranker protocol.

            This adapter provides a no-op reranking implementation that preserves
            the original order and scores of search results without modification.
            """

            def __init__(self) -> None:
                """Initialize the no-op reranker adapter."""
                self._inner = NoopReranker()

            def rerank(
                self,
                query: str,
                ids: Iterable[int],
                scores: Iterable[float],
            ) -> RerankResult:
                """Rerank results using the no-op reranker (preserves order).

                Parameters
                ----------
                query : str
                    Query text (unused by no-op reranker).
                ids : Iterable[int]
                    Document/chunk IDs to rerank.
                scores : Iterable[float]
                    Initial relevance scores.

                Returns
                -------
                RerankResult
                    Result containing the same IDs and scores in the same order,
                    as the no-op reranker does not modify results.
                """
                return self._inner.rerank(query, ids, scores)

        def _build_default_reranker() -> Reranker:
            """Build the default no-op reranker instance.

            Returns
            -------
            Reranker
                A no-op reranker adapter that preserves original result order
                and scores without modification.
            """
            return cast("Reranker", _NoopRerankerAdapter())

        return cls(
            run_stage0=run_stage0,
            decide_secondary_stage=decide_secondary_stage,
            hydrate_ids=_hydrate_ids,
            resolve_xtr_index=_resolve_xtr_index,
            late_interaction_factory=XTRLateInteraction,
            reranker_factory=_build_default_reranker,
        )


async def semantic_search_pro(
    context: ApplicationContext,
    query: str,
    limit: int = 20,
    options: SemanticProOptions | None = None,
    hooks: SemanticProHooks | None = None,
) -> AnswerEnvelope:
    """Execute Stage-0 → gating → optional late-interaction → optional rerank.

    Returns
    -------
    AnswerEnvelope
        Structured MCP response capturing findings and metadata.
    """
    return await asyncio.to_thread(_semantic_search_pro_sync, context, query, limit, options, hooks)


def _semantic_search_pro_sync(
    context: ApplicationContext,
    query: str,
    limit: int,
    options: SemanticProOptions | None,
    hooks: SemanticProHooks | None,
) -> AnswerEnvelope:
    """Execute synchronous two-stage semantic search with optional reranking.

    Parameters
    ----------
    context : ApplicationContext
        Application context providing access to search engines, catalog, XTR
        index, and configuration.
    query : str
        Query text to search for. Empty queries result in error envelopes.
    limit : int
        Maximum number of results to return. Clamped by context limits.
    options : SemanticProOptions | None, optional
        User-facing options controlling late-interaction, reranking, and
        explanation behavior. If None, uses defaults.
    hooks : SemanticProHooks | None, optional
        Runtime hooks for dependency injection. If None, uses default
        production implementations.

    Returns
    -------
    AnswerEnvelope
        Structured MCP response containing findings, method metadata, limits,
        confidence score, and stage execution details including gating decisions
        and optional late-interaction/reranking results.
    """
    hooks = hooks or SemanticProHooks.default()
    options = options or SemanticProOptions()
    query = (query or "").strip()
    if not query:
        return _error_envelope("missing query text")

    if options.stage_weights is not None:
        stage_weights = dict(options.stage_weights)
    else:
        stage_weights = context.hybrid_fusion_weights()
    limit = context.clamp_hybrid_limit(limit)
    stage0 = hooks.run_stage0(
        context.get_hybrid_engine(),
        query=query,
        semantic_hits=[],
        limit=limit,
        options=context.build_stage0_options(weights=stage_weights),
    )
    ids, scores = stage0.ids, stage0.scores

    decision = hooks.decide_secondary_stage(
        {
            "candidate_count": len(ids),
            "top_score": scores[0] if scores else 0.0,
            "margin": (scores[0] - scores[1]) if len(scores) > 1 else 0.0,
            "budget_ms": 0,
        },
        StageGateConfig(),
    )

    stage_ctx = _StageContext(
        context=context,
        options=options,
        decision=decision,
        stage_records=[],
        notes=list(stage0.warnings),
        hooks=hooks,
    )

    ids, scores = _run_late_interaction_stage(
        stage_ctx=stage_ctx,
        query=query,
        ids=ids,
        scores=scores,
    )

    ids, scores, reranker_summary = _run_reranker_stage(
        stage_ctx=stage_ctx,
        query=query,
        ids=ids,
        scores=scores,
    )

    with context.open_catalog() as catalog:
        findings = hooks.hydrate_ids(catalog, ids, scores)

    method = _build_method(
        stage0=stage0,
        decision=decision,
        notes=stage_ctx.notes,
        stages=stage_ctx.stage_records,
        reranker_summary=reranker_summary,
    )
    confidence = float(scores[0]) if scores else 0.0
    envelope: AnswerEnvelope = {
        "findings": findings,
        "method": method,
        "limits": [f"k={int(limit)}"],
        "answer": "",
        "confidence": confidence,
    }
    return envelope


def _hydrate_ids(
    catalog: DuckDBCatalog,
    ids: Sequence[int],
    scores: Sequence[float],
) -> list[Finding]:
    """Hydrate finding payloads from chunk IDs and scores using DuckDB catalog.

    Parameters
    ----------
    catalog : DuckDBCatalog
        DuckDB catalog instance for querying chunk metadata. Must have a
        "chunks" view or table available.
    ids : Sequence[int]
        Sequence of chunk IDs to hydrate, ordered by relevance.
    scores : Sequence[float]
        Sequence of relevance scores corresponding to each chunk ID. Must
        match the length of ids.

    Returns
    -------
    list[Finding]
        List of finding dictionaries containing chunk_id, score, and optionally
        title (URI) if available from the catalog. Returns empty list if ids
        is empty or the chunks relation does not exist.
    """
    if not ids:
        return []
    with catalog.connection() as conn:
        if not relation_exists(conn, "chunks"):
            return [
                _make_finding(int(chunk_id), float(score))
                for chunk_id, score in zip(ids, scores, strict=False)
            ]
        table = conn.execute(
            'SELECT id, uri FROM "chunks" AS c '
            "JOIN UNNEST(?) WITH ORDINALITY AS ordering(chunk_id, position)"
            " ON c.id = ordering.chunk_id ORDER BY ordering.position",
            [list(ids)],
        ).fetch_arrow_table()
        return [
            _make_finding(
                int(table.column(0)[rank].as_py()),
                float(scores[rank]),
                table.column(1)[rank].as_py(),
            )
            for rank in range(table.num_rows)
        ]


def _build_method(
    *,
    stage0: Stage0Result,
    decision: StageDecision,
    notes: list[str],
    stages: list[StageInfo],
    reranker_summary: MethodRerankerInfo | None,
) -> MethodInfo:
    """Assemble typed method metadata for the pro semantic search envelope.

    Parameters
    ----------
    stage0 : Stage0Result
        Result from Stage-0 hybrid search execution.
    decision : StageDecision
        Gating decision determining whether secondary stages ran.
    notes : list[str]
        List of warning or informational notes from execution.
    stages : list[StageInfo]
        List of stage execution records documenting late-interaction and
        reranking stage status.
    reranker_summary : MethodRerankerInfo | None, optional
        Optional reranker metadata if reranking was executed.

    Returns
    -------
    MethodInfo
        Structured method dictionary summarizing Stage-0, gating decisions,
        stage execution details, and optional reranker information.
    """
    gating: MethodGatingInfo = {
        "should_run_secondary_stage": decision.should_run,
        "reason": decision.reason,
    }
    method: MethodInfo = {
        "retrieval": ["hybrid"],
        "stage0": cast("Stage0MethodInfo", dict(stage0.method)),
        "gating": gating,
    }
    if notes:
        method["notes"] = list(notes)
    if stages:
        method["stages"] = stages
    if reranker_summary is not None:
        method["reranker"] = reranker_summary
    return method


@dataclass(slots=True)
class _StageContext:
    """Accumulator references shared across stage helpers."""

    context: ApplicationContext
    options: SemanticProOptions
    decision: StageDecision
    stage_records: list[StageInfo]
    notes: list[str]
    hooks: SemanticProHooks


def _run_late_interaction_stage(
    *,
    stage_ctx: _StageContext,
    query: str,
    ids: list[int],
    scores: list[float],
) -> tuple[list[int], list[float]]:
    """Execute the late-interaction stage when enabled and permitted.

    Returns
    -------
    tuple[list[int], list[float]]
        Updated identifiers and updated scores.
    """
    stage: StageInfo = {"name": "late_interaction"}
    if not stage_ctx.options.use_warp:
        stage["status"] = "skip"
        stage["reason"] = "disabled"
        stage_ctx.stage_records.append(stage)
        return ids, scores
    if not stage_ctx.decision.should_run:
        stage["status"] = "skip"
        stage["reason"] = "gated"
        stage_ctx.stage_records.append(stage)
        return ids, scores
    if not ids:
        stage["status"] = "skip"
        stage["reason"] = "no_candidates"
        stage_ctx.stage_records.append(stage)
        return ids, scores
    xtr_index = stage_ctx.hooks.resolve_xtr_index(stage_ctx.context)
    if xtr_index is None:
        stage["status"] = "skip"
        stage["reason"] = "xtr_unavailable"
        stage_ctx.stage_records.append(stage)
        stage_ctx.notes.append("late_interaction skipped: XTR unavailable")
        return ids, scores
    li = stage_ctx.hooks.late_interaction_factory(xtr_index)
    narrowed = li.rescore(
        query=query,
        candidate_ids=ids[: min(stage_ctx.options.xtr_k, len(ids))],
        explain=stage_ctx.options.explain,
    )
    stage["status"] = "run"
    stage["reason"] = "executed"
    stage_ctx.stage_records.append(stage)
    return narrowed.ids, narrowed.scores


def _run_reranker_stage(
    *,
    stage_ctx: _StageContext,
    query: str,
    ids: list[int],
    scores: list[float],
) -> tuple[list[int], list[float], MethodRerankerInfo | None]:
    """Execute the reranker stage when enabled and candidates exist.

    Returns
    -------
    tuple[list[int], list[float], MethodRerankerInfo | None]
        Updated identifiers, scores, and reranker summary when available.
    """
    stage: StageInfo = {"name": "reranker"}
    if not stage_ctx.options.use_reranker:
        stage["status"] = "skip"
        stage["reason"] = "disabled"
        stage_ctx.stage_records.append(stage)
        return ids, scores, None
    if not ids:
        stage["status"] = "skip"
        stage["reason"] = "no_candidates"
        stage_ctx.stage_records.append(stage)
        return ids, scores, None
    reranker = stage_ctx.hooks.reranker_factory()
    original = list(ids)
    reranked = reranker.rerank(query, ids, scores)
    reordered = sum(1 for idx, chunk_id in enumerate(reranked.ids) if chunk_id != original[idx])
    stage["status"] = "run"
    stage["reason"] = "executed"
    summary: MethodRerankerInfo = {
        "provider": "noop",
        "enabled": True,
        "reason": "executed",
        "reordered": reordered,
    }
    stage_ctx.stage_records.append(stage)
    return reranked.ids, reranked.scores, summary


def _make_finding(chunk_id: int, score: float, uri: str | None = None) -> Finding:
    """Create a minimal finding payload for hydrated chunks.

    Returns
    -------
    Finding
        Typed finding dictionary containing chunk identifier and score.
    """
    finding: Finding = {"chunk_id": int(chunk_id), "score": float(score)}
    if uri:
        finding["title"] = str(uri)
    return finding


def _resolve_xtr_index(context: ApplicationContext) -> XTRIndex | None:
    """Resolve the XTR index via runtime cells when available.

    Returns
    -------
    XTRIndex | None
        Ready XTR index instance when one exists.
    """
    runtime_cells = getattr(context, "runtime_cells", None)
    candidate = getattr(runtime_cells, "xtr_index", None) if runtime_cells is not None else None
    if isinstance(candidate, XTRIndex):
        return candidate
    return context.get_xtr_index()


def _error_envelope(reason: str) -> AnswerEnvelope:
    """Return a typed error envelope for invalid adapter inputs.

    Returns
    -------
    AnswerEnvelope
        Error envelope carrying the provided reason.
    """
    return cast("AnswerEnvelope", {"error": reason})


__all__ = [
    "ProOptions",
    "SemanticProHooks",
    "SemanticProOptions",
    "semantic_search_pro",
]
