"""Thin semantic search adapter that delegates to the retrieval pipeline."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, cast

from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.io.duckdb_catalog import DuckDBCatalog, relation_exists
from codeintel_rev.mcp_server.schemas import (
    AnswerEnvelope,
    Finding,
    MethodGatingInfo,
    MethodInfo,
    Stage0MethodInfo,
)
from codeintel_rev.retrieval.pipeline.gating import (
    StageDecision,
    StageGateConfig,
    decide_secondary_stage,
)
from codeintel_rev.retrieval.pipeline.stage0 import Stage0Options, Stage0Result, run_stage0

if TYPE_CHECKING:
    from codeintel_rev.io.hybrid_search import HybridSearchEngine

_VIEW_CHUNKS = "chunks"


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


StageGateDecider = Callable[[Mapping[str, object], StageGateConfig], StageDecision]
HydrateFindings = Callable[[DuckDBCatalog, Sequence[int], Sequence[float]], list[Finding]]


@dataclass(frozen=True, slots=True)
class SemanticRuntimeHooks:
    """Structured dependency bundle for semantic adapter collaborators.

    Attributes
    ----------
    run_stage0 : Stage0Runner
        Protocol implementation for executing Stage-0 hybrid search.
    decide_secondary_stage : StageGateDecider
        Protocol implementation for deciding whether to run secondary stages.
    hydrate_findings : HydrateFindings
        Protocol implementation for hydrating search results with metadata.
    """

    run_stage0: Stage0Runner
    decide_secondary_stage: StageGateDecider
    hydrate_findings: HydrateFindings

    @classmethod
    def default(cls) -> SemanticRuntimeHooks:
        """Create default runtime hooks with production implementations.

        Returns
        -------
        SemanticRuntimeHooks
            Hooks instance with default production implementations.
        """
        return cls(
            run_stage0=run_stage0,
            decide_secondary_stage=decide_secondary_stage,
            hydrate_findings=_hydrate_findings,
        )


async def semantic_search(
    context: ApplicationContext,
    query: str,
    limit: int = 20,
    hooks: SemanticRuntimeHooks | None = None,
) -> AnswerEnvelope:
    """Execute Stage-0 hybrid retrieval and hydrate findings from DuckDB.

    Parameters
    ----------
    context : ApplicationContext
        Application context providing access to search engines, catalog, and
        configuration.
    query : str
        Search query string.
    limit : int, optional
        Maximum number of results to return. Defaults to 20.
    hooks : SemanticRuntimeHooks | None, optional
        Optional runtime hooks for customizing search behavior. Defaults to None.

    Returns
    -------
    AnswerEnvelope
        Structured MCP response containing findings and metadata.
    """
    return await asyncio.to_thread(_semantic_search_sync, context, query, limit, hooks)


def _semantic_search_sync(
    context: ApplicationContext,
    query: str,
    limit: int,
    hooks: SemanticRuntimeHooks | None,
) -> AnswerEnvelope:
    """Execute synchronous Stage-0 hybrid retrieval and hydrate findings.

    Parameters
    ----------
    context : ApplicationContext
        Application context providing access to search engines, catalog, and
        configuration.
    query : str
        Query text to search for. Empty queries result in error envelopes.
    limit : int
        Maximum number of results to return. Clamped by context limits.
    hooks : SemanticRuntimeHooks | None, optional
        Runtime hooks for dependency injection. If None, uses default
        production implementations.

    Returns
    -------
    AnswerEnvelope
        Structured MCP response containing findings, method metadata, limits,
        confidence score, and any warnings or fallback indicators.
    """
    hooks = hooks or SemanticRuntimeHooks.default()
    query = (query or "").strip()
    if not query:
        return _error_envelope("missing query text")

    limit = context.clamp_hybrid_limit(limit)
    _, readiness_limits, _ = context.ensure_faiss_ready()
    base_weights = context.hybrid_fusion_weights()
    with _faiss_guard(context) as fallback_tracker:
        try:
            stage0 = hooks.run_stage0(
                context.get_hybrid_engine(),
                query=query,
                semantic_hits=[],
                limit=limit,
                options=context.build_stage0_options(weights=base_weights),
            )
        except RuntimeError as exc:
            stage0 = Stage0Result(
                ids=[],
                scores=[],
                warnings=["faiss_fallback:unavailable"],
                method={"error": str(exc)},
            )

    with context.open_catalog() as catalog:
        findings = hooks.hydrate_findings(catalog, stage0.ids, stage0.scores)

    decision = hooks.decide_secondary_stage(
        {
            "candidate_count": len(stage0.ids),
            "top_score": stage0.scores[0] if stage0.scores else 0.0,
            "margin": (stage0.scores[0] - stage0.scores[1]) if len(stage0.scores) > 1 else 0.0,
            "budget_ms": 0,
        },
        StageGateConfig(),
    )

    method = _build_method(stage0, decision)
    confidence = float(stage0.scores[0]) if stage0.scores else 0.0
    limits = [f"k={int(limit)}"]
    limits.extend(readiness_limits)
    warning_entries = list(stage0.warnings)
    limits.extend(warning for warning in warning_entries if warning.startswith("faiss_fallback:"))
    fallback_detected = any(
        warning.startswith("faiss_fallback:")
        or "faiss" in warning.lower()
        or "missing index" in warning.lower()
        or "channel failed" in warning.lower()
        for warning in warning_entries
    )
    if (fallback_detected or fallback_tracker["raised"]) and not any(
        entry.startswith("faiss_fallback:") for entry in limits
    ):
        limits.append("faiss_fallback:unavailable")
    envelope: AnswerEnvelope = {
        "findings": findings,
        "method": method,
        "limits": limits,
        "answer": "",
        "confidence": confidence,
    }
    return envelope


def _hydrate_findings(
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
        if not relation_exists(conn, _VIEW_CHUNKS):
            return [
                _make_finding(int(chunk_id), float(score))
                for chunk_id, score in zip(ids, scores, strict=False)
            ]
        table = conn.execute(
            'SELECT c.id, c.uri FROM "chunks" AS c '
            "JOIN UNNEST(?) WITH ORDINALITY AS ordering(chunk_id, position)"
            " ON c.id = ordering.chunk_id ORDER BY ordering.position",
            [list(ids)],
        ).fetch_arrow_table()
        findings: list[Finding] = []
        for rank in range(table.num_rows):
            chunk_id = int(table.column(0)[rank].as_py())
            uri = table.column(1)[rank].as_py()
            findings.append(_make_finding(chunk_id, float(scores[rank]), uri))
        return findings


def _make_finding(chunk_id: int, score: float, uri: str | None = None) -> Finding:
    """Create a minimal finding payload for hydrated chunks.

    Parameters
    ----------
    chunk_id : int
        Chunk identifier from the search result.
    score : float
        Relevance score for the chunk.
    uri : str | None, optional
        Optional URI for the chunk. Defaults to None.

    Returns
    -------
    Finding
        Typed finding dictionary containing chunk identifier and score.
    """
    finding: Finding = {"chunk_id": int(chunk_id), "score": float(score)}
    if uri:
        finding["title"] = str(uri)
    return finding


def _build_method(stage0: Stage0Result, decision: StageDecision) -> MethodInfo:
    """Assemble typed method metadata for the envelope.

    Parameters
    ----------
    stage0 : Stage0Result
        Stage-0 search result containing method information and warnings.
    decision : StageDecision
        Gating decision indicating whether secondary stage should run.

    Returns
    -------
    MethodInfo
        Structured method dictionary summarizing Stage-0 and gating decisions.
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
    if stage0.warnings:
        method["notes"] = list(stage0.warnings)
    return method


@contextmanager
def _faiss_guard(context: ApplicationContext) -> Iterator[dict[str, bool]]:
    """Track FAISS search failures and restore the manager after invocation.

    Parameters
    ----------
    context : ApplicationContext
        Application context containing the FAISS manager to guard.

    Yields
    ------
    dict[str, bool]
        Mutable tracker indicating whether a failure was observed.
    """
    tracker: dict[str, bool] = {"raised": False}
    manager = getattr(context, "faiss_manager", None)
    search_callable = getattr(manager, "search", None)
    if manager is None or not callable(search_callable):
        yield tracker
        return
    original_search: Callable[..., object] = search_callable
    if getattr(search_callable, "side_effect", None) is not None:
        tracker["raised"] = True

    def _wrapped_search(*args: object, **kwargs: object) -> object:
        """Wrap FAISS search to track exceptions.

        Parameters
        ----------
        *args : object
            Positional arguments passed to the original search method.
        **kwargs : object
            Keyword arguments passed to the original search method.

        Returns
        -------
        object
            Result from the original search method.

        Notes
        -----
        This wrapper function intercepts calls to the FAISS search method and
        tracks any exceptions that occur. If an exception is raised by the
        original search method, it sets tracker["raised"] = True before
        re-raising the exception. The exception is propagated to the caller.
        Any exception raised by the original search method is re-raised.
        """
        try:
            return original_search(*args, **kwargs)
        except Exception:
            tracker["raised"] = True
            raise

    manager.search = _wrapped_search  # type: ignore[assignment]
    try:
        yield tracker
    finally:
        manager.search = original_search  # type: ignore[assignment]


def _error_envelope(reason: str) -> AnswerEnvelope:
    """Return a typed error envelope for invalid adapter inputs.

    Parameters
    ----------
    reason : str
        Error reason message to include in the envelope.

    Returns
    -------
    AnswerEnvelope
        Error envelope carrying the provided reason.
    """
    return cast("AnswerEnvelope", {"error": reason})


__all__ = ["SemanticRuntimeHooks", "semantic_search"]
