"""Semantic search adapter using FAISS GPU and DuckDB.

Implements semantic code search by embedding queries and searching
the FAISS index, then hydrating results from DuckDB.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, cast

import httpx
import numpy as np

from codeintel_rev.app.middleware import get_session_id
from codeintel_rev.io.faiss_manager import FAISSManager
from codeintel_rev.io.vllm_client import VLLMClient
from codeintel_rev.mcp_server.common.observability import Observation, observe_duration
from codeintel_rev.mcp_server.schemas import (
    AnswerEnvelope,
    Finding,
    MethodInfo,
    ScopeIn,
)
from codeintel_rev.mcp_server.scope_utils import get_effective_scope
from kgfoundry_common.errors import EmbeddingError, VectorSearchError
from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    from codeintel_rev.app.config_context import ApplicationContext

SNIPPET_PREVIEW_CHARS = 500
COMPONENT_NAME = "codeintel_mcp"
LOGGER = get_logger(__name__)


@dataclass(frozen=True)
class _ScopeFilterFlags:
    """Aggregated boolean flags describing the active scope filters."""

    has_include_globs: bool
    has_exclude_globs: bool
    has_languages: bool

    @classmethod
    def from_scope(cls, scope: ScopeIn | None) -> _ScopeFilterFlags:
        """Create flags from an optional ``ScopeIn`` dictionary.

        Parameters
        ----------
        scope : ScopeIn | None
            Optional scope dictionary containing include_globs, exclude_globs,
            or languages keys.

        Returns
        -------
        _ScopeFilterFlags
            Flags instance indicating which scope filters are present.
        """
        return cls(
            has_include_globs=bool(scope and scope.get("include_globs")),
            has_exclude_globs=bool(scope and scope.get("exclude_globs")),
            has_languages=bool(scope and scope.get("languages")),
        )

    @property
    def has_filters(self) -> bool:
        """Return ``True`` when any of the scope filters are active."""
        return self.has_include_globs or self.has_exclude_globs or self.has_languages


@dataclass(frozen=True)
class _FaissFanout:
    """FAISS fan-out plan produced for a semantic search request."""

    faiss_k: int
    faiss_k_target: int


@dataclass(frozen=True)
class _HybridSearchState:
    """Encapsulate the outputs of FAISS prior to hybrid re-ranking."""

    query: str
    result_ids: Sequence[int]
    result_scores: Sequence[float]
    effective_limit: int


@dataclass(frozen=True)
class _HybridResult:
    """Hydration payload returned after hybrid re-ranking."""

    hydration_ids: list[int]
    hydration_scores: list[float]
    contribution_map: dict[int, list[tuple[str, int, float]]] | None
    retrieval_channels: list[str]


@dataclass(frozen=True)
class _SearchBudget:
    """Typed representation of the effective limit and metadata."""

    effective_limit: int
    max_results: int
    limits_metadata: tuple[str, ...]


@dataclass(frozen=True)
class _MethodContext:
    """Inputs required to build method metadata."""

    findings_count: int
    requested_limit: int
    effective_limit: int
    start_time: float
    retrieval_channels: Sequence[str]


async def semantic_search(
    context: ApplicationContext, query: str, limit: int = 20
) -> AnswerEnvelope:
    """Perform semantic search using embeddings.

    Applies session scope filters during DuckDB hydration (if scope has path/language
    constraints). FAISS search is performed without scope constraints (FAISS has no
    built-in filtering), then results are filtered via DuckDB catalog queries.

    Parameters
    ----------
    context : ApplicationContext
        Application context containing FAISS manager, vLLM client, and settings.
    query : str
        Search query text.
    limit : int, optional
        Maximum number of results to return. Defaults to 20.

    Returns
    -------
    AnswerEnvelope
        Semantic search response payload with findings and applied scope.

    Notes
    -----
    This function delegates to ``_semantic_search_sync`` which may raise
    ``VectorSearchError`` or ``EmbeddingError``. Those exceptions are not
    explicitly caught or re-raised by this async wrapper function.

    Examples
    --------
    Basic usage:

    >>> result = await semantic_search(context, "data processing")
    >>> isinstance(result["findings"], list)
    True

    With session scope:

    >>> set_scope(context, {"languages": ["python"], "include_globs": ["src/**"]})
    >>> result = await semantic_search(context, "data processing")
    >>> # Returns only Python chunks from src/ directory
    >>> result["scope"]["languages"]
    ['python']

    Notes
    -----
    Scope Integration:
    - Session scope is retrieved from registry using session ID (set by middleware).
    - FAISS search is performed without scope constraints (FAISS has no built-in filtering).
    - Chunk IDs from FAISS are filtered via DuckDB catalog using scope's `include_globs`,
      `exclude_globs`, and `languages` (see `query_by_filters` method).
    - Applied scope is included in response envelope (`scope` field) for transparency.
    - If no scope is set, searches all indexed chunks without filtering.
    """
    session_id = get_session_id()
    scope = await get_effective_scope(context, session_id)
    return await asyncio.to_thread(
        _semantic_search_sync,
        context,
        query,
        limit,
        session_id,
        scope,
    )


def _semantic_search_sync(
    context: ApplicationContext,
    query: str,
    limit: int,
    session_id: str,
    scope: ScopeIn | None,
) -> AnswerEnvelope:
    start_time = perf_counter()
    with observe_duration("semantic_search", COMPONENT_NAME) as observation:
        scope_flags = _ScopeFilterFlags.from_scope(scope)

        LOGGER.debug(
            "Semantic search with scope",
            extra={
                "session_id": session_id,
                "query": query,
                "has_scope": scope is not None,
                "scope_languages": (
                    cast("Sequence[str] | None", scope.get("languages"))
                    if scope
                    else None
                ),
                "scope_include_globs": scope.get("include_globs") if scope else None,
            },
        )

        budget = _build_search_budget(context, limit, observation)
        limits_metadata = [*budget.limits_metadata]

        multiplier = max(1, context.settings.limits.semantic_overfetch_multiplier)
        fanout = _calculate_faiss_fanout(
            budget.effective_limit,
            budget.max_results,
            multiplier,
            scope_flags,
        )
        if fanout.faiss_k < fanout.faiss_k_target:
            limits_metadata.append(
                f"FAISS fan-out clamped to {fanout.faiss_k} (max_results={budget.max_results})."
            )

        LOGGER.debug(
            "Computed FAISS fan-out",
            extra={
                "requested_limit": limit,
                "effective_limit": budget.effective_limit,
                "faiss_k": fanout.faiss_k,
                "faiss_k_target": fanout.faiss_k_target,
                "multiplier": multiplier,
                "has_scope_filters": scope_flags.has_filters,
                "has_include_globs": scope_flags.has_include_globs,
                "has_exclude_globs": scope_flags.has_exclude_globs,
                "has_languages": scope_flags.has_languages,
            },
        )

        result_ids, result_scores = _run_faiss_search_or_raise(
            context,
            _embed_query_or_raise(
                context.vllm_client,
                query,
                observation,
                context.settings.vllm.base_url,
            ),
            fanout.faiss_k,
            context.settings.index.faiss_nprobe,
            observation,
        )

        hybrid_result = _resolve_hybrid_results(
            context,
            _HybridSearchState(
                query, result_ids, result_scores, budget.effective_limit
            ),
            limits_metadata,
            ("semantic", "faiss"),
        )

        findings, hydrate_exc = _hydrate_findings(
            context,
            hybrid_result.hydration_ids,
            hybrid_result.hydration_scores,
            scope=scope,
        )
        _ensure_hydration_success(hydrate_exc, observation, context)

        observation.mark_success()

        _warn_scope_filter_reduction(
            scope,
            scope_flags,
            len(findings),
            budget.effective_limit,
            len(result_ids),
        )
        _annotate_hybrid_contributions(
            findings,
            hybrid_result.contribution_map,
            context.settings.index.rrf_k,
        )

        extras = _build_response_extras(
            _MethodContext(
                len(findings),
                limit,
                budget.effective_limit,
                start_time,
                hybrid_result.retrieval_channels,
            ),
            limits_metadata,
            scope,
        )

        answer_message = (
            f"Found {len(findings)} hybrid results for: {query}"
            if any(
                channel in {"bm25", "splade"}
                for channel in hybrid_result.retrieval_channels
            )
            else f"Found {len(findings)} semantically similar code chunks for: {query}"
        )

        return _make_envelope(
            findings=findings,
            answer=answer_message,
            confidence=0.85 if findings else 0.0,
            extras=extras,
        )


def _clamp_result_limit(
    requested_limit: int, max_results: int
) -> tuple[int, list[str]]:
    """Enforce bounds on requested limit with explanatory metadata.

    Parameters
    ----------
    requested_limit : int
        Client supplied limit from the API call.
    max_results : int
        Globally configured maximum number of results.

    Returns
    -------
    tuple[int, list[str]]
        Adjusted limit and zero or more informational messages describing why
        truncation occurred.
    """
    messages: list[str] = []
    if requested_limit <= 0:
        messages.append(
            f"Requested limit {requested_limit} is not positive; using minimum of 1."
        )
    if requested_limit > max_results:
        messages.append(
            f"Requested limit {requested_limit} exceeds max_results {max_results}; "
            f"truncating to {max_results}."
        )

    effective_limit = max(1, min(requested_limit, max_results))
    return effective_limit, messages


def _build_search_budget(
    context: ApplicationContext,
    requested_limit: int,
    observation: Observation,
) -> _SearchBudget:
    """Combine limit clamping and FAISS readiness metadata for a search.

    Parameters
    ----------
    context : ApplicationContext
        Application context providing settings and FAISS manager.
    requested_limit : int
        Requested result limit from client.
    observation : Observation
        Observation block used to mark errors.

    Returns
    -------
    _SearchBudget
        Search budget containing effective limit, max results, and limits metadata.

    Raises
    ------
    VectorSearchError
        If FAISS index is not ready or unavailable.
    """
    max_results = max(1, context.settings.limits.max_results)
    effective_limit, clamp_messages = _clamp_result_limit(requested_limit, max_results)

    ready, faiss_limits, faiss_error = context.ensure_faiss_ready()
    if not ready:
        observation.mark_error()
        raise VectorSearchError(
            faiss_error or "Semantic search not available - index not built",
            context={"faiss_index": str(context.paths.faiss_index)},
        )

    limits_metadata = (*faiss_limits, *clamp_messages)
    return _SearchBudget(effective_limit, max_results, limits_metadata)


def _calculate_faiss_fanout(
    effective_limit: int,
    max_results: int,
    multiplier: int,
    scope_flags: _ScopeFilterFlags,
) -> _FaissFanout:
    """Compute FAISS fan-out (k) and the target expansion for filtering.

    Parameters
    ----------
    effective_limit : int
        Limit after applying clamping rules.
    max_results : int
        System-wide cap on FAISS results.
    multiplier : int
        Semantic over-fetch multiplier configured in settings.
    scope_flags : _ScopeFilterFlags
        Flags describing whether scope filters are active.

    Returns
    -------
    _FaissFanout
        Fan-out plan containing both the actual FAISS ``k`` and the unclamped
        ``k`` target prior to ``max_results`` enforcement.
    """
    faiss_k_target = effective_limit
    if scope_flags.has_filters:
        faiss_k_target = effective_limit * multiplier
        faiss_k_target += _overfetch_bonus(effective_limit, scope_flags)

    faiss_k = max(
        effective_limit,
        min(max_results, faiss_k_target),
    )
    return _FaissFanout(faiss_k, faiss_k_target)


def _overfetch_bonus(effective_limit: int, scope_flags: _ScopeFilterFlags) -> int:
    """Determine additional fan-out when scope filters may drop results.

    Calculates an over-fetch bonus to compensate for results that may be filtered
    out by scope filters (include/exclude globs, language filters). The bonus
    is higher when multiple filter types are active, as more results are likely
    to be filtered out.

    Parameters
    ----------
    effective_limit : int
        Base number of results requested by the user.
    scope_flags : _ScopeFilterFlags
        Flags indicating which types of scope filters are active (include globs,
        exclude globs, language filters).

    Returns
    -------
    int
        Additional results to fetch beyond effective_limit to account for filtering.
        Returns effective_limit when both glob and language filters are active,
        effective_limit // 2 when only one type is active, or 0 when no filters
        are active.
    """
    if scope_flags.has_include_globs and scope_flags.has_languages:
        return effective_limit
    if scope_flags.has_include_globs or scope_flags.has_languages:
        return max(1, effective_limit // 2)
    return 0


def _resolve_hybrid_results(
    context: ApplicationContext,
    state: _HybridSearchState,
    limits_metadata: list[str],
    retrieval_channels: Sequence[str],
) -> _HybridResult:
    """Join hybrid retrieval results with the FAISS output when available.

    Parameters
    ----------
    context : ApplicationContext
        Application context that can provide the hybrid search engine.
    state : _HybridSearchState
        FAISS search state carrying IDs, scores, query text, and applied limit.
    limits_metadata : list[str]
        Mutable metadata bucket for reporting search limitations.
    retrieval_channels : Sequence[str]
        Base retrieval channels (semantic + FAISS).

    Returns
    -------
    _HybridResult
        Hydration IDs, scores, optional hybrid contributions, and the final list of
        retrieval channels that contributed to the answer.
    """
    hydration_ids = list(state.result_ids)
    hydration_scores = list(state.result_scores)
    contribution_map: dict[int, list[tuple[str, int, float]]] | None = None
    channels_out = list(retrieval_channels)

    try:
        hybrid_engine = context.get_hybrid_engine()
    except RuntimeError as exc:  # pragma: no cover - defensive
        limits_metadata.append(f"Hybrid search unavailable: {exc}")
        LOGGER.warning("Hybrid engine unavailable", exc_info=exc)
        return _build_hybrid_result(
            hydration_ids,
            hydration_scores,
            state.effective_limit,
            contribution_map,
            channels_out,
        )

    if hybrid_engine is None:
        return _build_hybrid_result(
            hydration_ids,
            hydration_scores,
            state.effective_limit,
            contribution_map,
            channels_out,
        )

    hybrid_result = hybrid_engine.search(
        query=state.query,
        semantic_ids=state.result_ids,
        semantic_scores=state.result_scores,
        limit=state.effective_limit,
    )
    if hybrid_result.warnings:
        limits_metadata.extend(hybrid_result.warnings)

    fused_ids: list[int] = []
    fused_scores: list[float] = []
    fused_contributions: dict[int, list[tuple[str, int, float]]] = {}
    for doc in hybrid_result.docs:
        try:
            chunk_id_int = int(doc.doc_id)
        except ValueError:
            limits_metadata.append(
                f"Hybrid result skipped (non-numeric chunk id): {doc.doc_id}"
            )
            continue

        fused_ids.append(chunk_id_int)
        fused_scores.append(float(doc.score))
        fused_contributions[chunk_id_int] = hybrid_result.contributions.get(
            doc.doc_id, []
        )

    if fused_ids:
        channels_out = list(
            dict.fromkeys(["semantic", "faiss", *hybrid_result.channels])
        )
        return _build_hybrid_result(
            fused_ids,
            fused_scores,
            state.effective_limit,
            fused_contributions,
            channels_out,
        )
    return _build_hybrid_result(
        hydration_ids,
        hydration_scores,
        state.effective_limit,
        contribution_map,
        channels_out,
    )


def _build_hybrid_result(
    hydration_ids: list[int],
    hydration_scores: list[float],
    limit: int,
    contribution_map: dict[int, list[tuple[str, int, float]]] | None,
    retrieval_channels: Sequence[str],
) -> _HybridResult:
    """Trim FAISS/hybrid candidates to the effective limit.

    Parameters
    ----------
    hydration_ids : list[int]
        Candidate IDs to trim.
    hydration_scores : list[float]
        Candidate scores corresponding to IDs.
    limit : int
        Maximum number of results to return.
    contribution_map : dict[int, list[tuple[str, int, float]]] | None
        Optional contribution map for hybrid results.
    retrieval_channels : Sequence[str]
        List of retrieval channels used.

    Returns
    -------
    _HybridResult
        Trimmed result with IDs, scores, contribution map, and channels.
    """
    trimmed_ids = hydration_ids[:limit]
    trimmed_scores = hydration_scores[: len(trimmed_ids)]
    return _HybridResult(
        trimmed_ids,
        trimmed_scores,
        contribution_map,
        list(retrieval_channels),
    )


def _embed_query_or_raise(
    client: VLLMClient,
    query: str,
    observation: Observation,
    vllm_url: str,
) -> np.ndarray:
    """Embed text or raise with a structured embedding error.

    Parameters
    ----------
    client : VLLMClient
        vLLM client used to emit the embedding.
    query : str
        Query text to embed.
    observation : Observation
        Duration observation used for marking failure.
    vllm_url : str
        URL used for diagnostics in error contexts.

    Returns
    -------
    np.ndarray
        Normalized query vector with shape (1, dim).

    Raises
    ------
    EmbeddingError
        If embedding fails or service is unavailable.
    """
    embedding, embed_error = _embed_query(client, query)
    if embedding is None or embed_error is not None:
        observation.mark_error()
        raise EmbeddingError(
            embed_error or "Embedding service unavailable",
            context={"vllm_url": vllm_url},
        )

    return embedding


def _run_faiss_search_or_raise(
    context: ApplicationContext,
    query_vector: np.ndarray,
    limit: int,
    nprobe: int,
    observation: Observation,
) -> tuple[list[int], list[float]]:
    """Perform FAISS search and raise when the index search fails.

    Parameters
    ----------
    context : ApplicationContext
        Application context providing the FAISS manager and metadata.
    query_vector : np.ndarray
        Query vector produced by the embedding service.
    limit : int
        Requested fan-out.
    nprobe : int
        Number of IVF cells to probe.
    observation : Observation
        Observation block used to mark errors.

    Returns
    -------
    tuple[list[int], list[float]]
        Chunk identifiers and their similarity scores.

    Raises
    ------
    VectorSearchError
        If FAISS search fails.
    """
    result_ids, result_scores, search_exc = _run_faiss_search(
        context.faiss_manager,
        query_vector,
        limit,
        nprobe=nprobe,
    )
    if search_exc is not None:
        observation.mark_error()
        raise VectorSearchError(
            str(search_exc),
            cause=search_exc,
            context={"faiss_index": str(context.paths.faiss_index)},
        )

    return result_ids, result_scores


def _ensure_hydration_success(
    hydrate_exc: Exception | None,
    observation: Observation,
    context: ApplicationContext,
) -> None:
    """Stop execution when DuckDB hydration fails.

    Parameters
    ----------
    hydrate_exc : Exception | None
        Exception returned from ``_hydrate_findings``.
    observation : Observation
        Observation used to mark the duration as failed.
    context : ApplicationContext
        Context for building error metadata.

    Raises
    ------
    VectorSearchError
        If hydration fails.
    """
    if hydrate_exc is None:
        return

    observation.mark_error()
    raise VectorSearchError(
        str(hydrate_exc),
        cause=hydrate_exc,
        context={
            "duckdb_path": str(context.paths.duckdb_path),
            "vectors_dir": str(context.paths.vectors_dir),
        },
    )


def _warn_scope_filter_reduction(
    scope: ScopeIn | None,
    scope_flags: _ScopeFilterFlags,
    findings_count: int,
    effective_limit: int,
    faiss_result_count: int,
) -> None:
    """Log when scope filtering reduces the result set below the requested limit.

    Parameters
    ----------
    scope : ScopeIn | None
        Applied scope configuration.
    scope_flags : _ScopeFilterFlags
        Flags describing the active scope filters.
    findings_count : int
        Number of findings returned to the client.
    effective_limit : int
        Limit applied after clamping.
    faiss_result_count : int
        Number of results returned from FAISS prior to filtering.
    """
    if not (scope and scope_flags.has_filters and findings_count < effective_limit):
        return

    LOGGER.warning(
        "Scope filtering reduced results below requested limit",
        extra={
            "requested_limit": effective_limit,
            "actual_count": findings_count,
            "faiss_results": faiss_result_count,
            "has_include_globs": scope_flags.has_include_globs,
            "has_exclude_globs": scope_flags.has_exclude_globs,
            "has_languages": scope_flags.has_languages,
        },
    )


def _annotate_hybrid_contributions(
    findings: list[Finding],
    contribution_map: dict[int, list[tuple[str, int, float]]] | None,
    rrf_k: int,
) -> None:
    """Attach hybrid contribution narratives to findings when available.

    Parameters
    ----------
    findings : list[Finding]
        Findings returned to the client.
    contribution_map : dict[int, list[tuple[str, int, float]]] | None
        Contribution information keyed by chunk id.
    rrf_k : int
        Reciprocal rank fusion parameter used for the narrative.
    """
    if not contribution_map:
        return

    for finding in findings:
        chunk_id_value = finding.get("chunk_id")
        if chunk_id_value is None:
            continue
        contributions = contribution_map.get(int(chunk_id_value))
        if not contributions:
            continue

        parts = [f"{channel} rank={rank}" for channel, rank, _ in contributions]
        finding["why"] = f"Hybrid RRF (k={rrf_k}): " + ", ".join(parts)


def _embed_query(
    client: VLLMClient, query: str
) -> tuple[np.ndarray | None, str | None]:
    """Embed query text and return a normalized vector and error message.

    Parameters
    ----------
    client : VLLMClient
        vLLM client for generating embeddings.
    query : str
        Query text to embed.

    Returns
    -------
    tuple[np.ndarray | None, str | None]
        Pair of (query_vector, error_message). Exactly one element will be ``None``.
    """
    try:
        vector = client.embed_single(query)
    except (RuntimeError, ValueError, httpx.HTTPError) as exc:
        return None, f"Embedding service unavailable: {exc}"

    array = np.array(vector, dtype=np.float32).reshape(1, -1)
    return array, None


def _run_faiss_search(
    faiss_mgr: FAISSManager,
    query_vector: np.ndarray,
    limit: int,
    *,
    nprobe: int,
) -> tuple[list[int], list[float], Exception | None]:
    """Execute FAISS search and return result identifiers and scores.

    Parameters
    ----------
    faiss_mgr : FAISSManager
        FAISS index manager instance.
    query_vector : np.ndarray
        Query vector of shape (1, vec_dim).
    limit : int
        Maximum number of results to return.
    nprobe : int
        Number of IVF cells to probe during the search. Higher values improve
        recall at the cost of latency. Passed directly to
        :meth:`FAISSManager.search`.

    Returns
    -------
    tuple[list[int], list[float], Exception | None]
        Tuple of (chunk_ids, distances, error). ``error`` is ``None`` when the
        search succeeds; otherwise it contains the triggering exception.
    """
    try:
        distances, ids = faiss_mgr.search(query_vector, k=limit, nprobe=nprobe)
    except RuntimeError as exc:
        return [], [], exc

    return ids[0].tolist(), distances[0].tolist(), None


def _hydrate_findings(
    context: ApplicationContext,
    chunk_ids: Sequence[int],
    scores: Sequence[float],
    *,
    scope: ScopeIn | None = None,
) -> tuple[list[Finding], Exception | None]:
    """Hydrate FAISS search results from DuckDB.

    Applies scope filters (path globs, languages) during chunk hydration if scope
    is provided. FAISS search is performed without scope constraints, then results
    are filtered via DuckDB catalog queries.

    Parameters
    ----------
    context : ApplicationContext
        Application context for accessing DuckDB catalog.
    chunk_ids : Sequence[int]
        Chunk identifiers from FAISS search.
    scores : Sequence[float]
        Similarity scores aligned with chunk_ids.
    scope : ScopeIn | None, optional
        Session scope with optional `include_globs`, `exclude_globs`, and `languages`
        fields. If provided and contains filters, uses `query_by_filters` instead of
        `query_by_ids`. Defaults to None.

    Returns
    -------
    tuple[list[Finding], Exception | None]
        Findings constructed from the catalog and optional hydration exception.

    Notes
    -----
    Scope Filtering:
    - If scope has `include_globs`, `exclude_globs`, or `languages`, uses
      `catalog.query_by_filters()` to filter chunks by path patterns and file
      extensions.
    - If scope is None or has no filters, uses `catalog.query_by_ids()` for
      unfiltered retrieval (backward compatible).
    - Filtering happens during DuckDB hydration (post-FAISS), so FAISS search
      may return more IDs than needed to compensate for filtering.
    """
    findings: list[Finding] = []
    try:
        with context.open_catalog() as catalog:
            valid_ids = [int(chunk_id) for chunk_id in chunk_ids if chunk_id >= 0]
            if not valid_ids:
                return [], None

            include_globs: list[str] | None
            exclude_globs: list[str] | None
            languages: list[str] | None
            if scope:
                include_globs = scope.get("include_globs")
                exclude_globs = scope.get("exclude_globs")
                languages = scope.get("languages")
            else:
                include_globs = None
                exclude_globs = None
                languages = None

            has_filters = bool(include_globs or exclude_globs or languages)

            # Apply scope filters if scope has path/language constraints
            if has_filters:
                records = catalog.query_by_filters(
                    valid_ids,
                    include_globs=include_globs,
                    exclude_globs=exclude_globs,
                    languages=languages,
                )
                LOGGER.debug(
                    "Applied scope filters during DuckDB hydration",
                    extra={
                        "chunk_ids_count": len(valid_ids),
                        "filtered_count": len(records),
                        "has_include_globs": bool(include_globs),
                        "has_exclude_globs": bool(exclude_globs),
                        "has_languages": bool(languages),
                    },
                )
            else:
                records = catalog.query_by_ids(valid_ids)
            chunk_by_id = {
                int(record["id"]): record for record in records if "id" in record
            }

            for chunk_id, score in zip(chunk_ids, scores, strict=True):
                if chunk_id < 0:
                    continue
                chunk = chunk_by_id.get(int(chunk_id))
                if not chunk:
                    continue

                finding: Finding = {
                    "type": "usage",
                    "title": f"{Path(chunk['uri']).name} (score: {score:.3f})",
                    "location": {
                        "uri": chunk["uri"],
                        "start_line": chunk["start_line"],
                        "start_column": 0,
                        "end_line": chunk["end_line"],
                        "end_column": 0,
                    },
                    "snippet": chunk["preview"][:SNIPPET_PREVIEW_CHARS],
                    "score": float(score),
                    "why": f"Semantic similarity: {score:.3f}",
                    "chunk_id": int(chunk_id),
                }
                findings.append(finding)
    except (RuntimeError, OSError) as exc:
        return findings, exc

    return findings, None


def _build_method(
    findings_count: int,
    requested_limit: int,
    effective_limit: int,
    start_time: float,
    retrieval_channels: Sequence[str],
) -> MethodInfo:
    """Build method metadata for the response.

    Parameters
    ----------
    findings_count : int
        Number of findings returned.
    requested_limit : int
        Requested result limit.
    effective_limit : int
        Effective limit applied after clamping.
    start_time : float
        Search start time (monotonic clock).
    retrieval_channels : Sequence[str]
        Retrieval systems that contributed to the final result set.

    Returns
    -------
    MethodInfo
        Retrieval metadata describing semantic search coverage.
    """
    elapsed_ms = int((perf_counter() - start_time) * 1000)
    coverage = f"{findings_count}/{effective_limit} results in {elapsed_ms}ms"
    if requested_limit != effective_limit:
        coverage = f"{coverage} (requested {requested_limit})"
    return {
        "retrieval": list(dict.fromkeys(retrieval_channels)),
        "coverage": coverage,
    }


def _make_envelope(
    *,
    findings: Sequence[Finding],
    answer: str,
    confidence: float,
    extras: dict[str, object] | None = None,
) -> AnswerEnvelope:
    """Construct an AnswerEnvelope with optional metadata.

    Parameters
    ----------
    findings : Sequence[Finding]
        Search findings.
    answer : str
        Answer text.
    confidence : float
        Confidence score (0.0 to 1.0).
    extras : dict[str, object] | None, optional
        Additional envelope fields (for example ``limits``, ``method``, or
        ``problem`` metadata). Defaults to None.

    Returns
    -------
    AnswerEnvelope
        Response payload ready for MCP clients.
    """
    # Build envelope with all fields at once for type safety
    # AnswerEnvelope is TypedDict with total=False, so all fields are optional
    # We construct the envelope by unpacking extras if present
    base_envelope = {
        "answer": answer,
        "query_kind": "semantic",
        "findings": list(findings),
        "confidence": confidence,
    }

    if extras:
        # Include extras in initial construction using dict unpacking
        # We use cast to tell the type checker that extras contains valid AnswerEnvelope keys
        # This is safe because _success_extras() only returns valid AnswerEnvelope keys
        envelope: AnswerEnvelope = cast(
            "AnswerEnvelope",
            {**base_envelope, **extras},
        )
    else:
        envelope = cast("AnswerEnvelope", base_envelope)

    return envelope


def _success_extras(
    limits: Sequence[str],
    method: MethodInfo,
) -> dict[str, object]:
    """Build a success extras payload with optional limits metadata.

    Parameters
    ----------
    limits : Sequence[str]
        Search limitations or warnings.
    method : MethodInfo
        Retrieval metadata to include in the response.

    Returns
    -------
    dict[str, object]
        Extras payload including method metadata and optional limits.
    """
    extras: dict[str, object] = {"method": method}
    if limits:
        extras["limits"] = list(limits)
    return extras


def _build_response_extras(
    context: _MethodContext,
    limits: Sequence[str],
    scope: ScopeIn | None,
) -> dict[str, object]:
    """Build extras payload including method metadata and optional scope.

    Parameters
    ----------
    context : _MethodContext
        Context values required to build method metadata.
    limits : Sequence[str]
        Search limitations or warnings.
    scope : ScopeIn | None
        Optional scope configuration to include in extras.

    Returns
    -------
    dict[str, object]
        Extras payload dictionary containing method metadata and optional scope.
    """
    method_metadata = _build_method(
        context.findings_count,
        context.requested_limit,
        context.effective_limit,
        context.start_time,
        context.retrieval_channels,
    )
    extras = _success_extras(limits, method_metadata)
    if scope:
        extras["scope"] = scope
    return extras


__all__ = ["semantic_search"]
