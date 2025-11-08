"""Semantic search adapter using FAISS GPU and DuckDB.

Implements semantic code search by embedding queries and searching
the FAISS index, then hydrating results from DuckDB.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, cast

import httpx
import numpy as np

from codeintel_rev.app.middleware import get_session_id
from codeintel_rev.io.faiss_manager import FAISSManager
from codeintel_rev.io.vllm_client import VLLMClient
from codeintel_rev.mcp_server.schemas import AnswerEnvelope, Finding, MethodInfo, ScopeIn
from codeintel_rev.mcp_server.scope_utils import get_effective_scope
from kgfoundry_common.errors import EmbeddingError, VectorSearchError
from kgfoundry_common.logging import get_logger
from kgfoundry_common.observability import DurationObservation, MetricsProvider, observe_duration

if TYPE_CHECKING:
    from codeintel_rev.app.config_context import ApplicationContext

SNIPPET_PREVIEW_CHARS = 500
COMPONENT_NAME = "codeintel_mcp"
LOGGER = get_logger(__name__)
METRICS = MetricsProvider.default()


def _supports_histogram_labels(histogram: object) -> bool:
    labelnames = getattr(histogram, "_labelnames", None)
    if labelnames is None:
        return True
    try:
        return len(tuple(labelnames)) > 0
    except TypeError:
        return False


_METRICS_ENABLED = _supports_histogram_labels(METRICS.operation_duration_seconds)


class _NoopObservation:
    """Fallback observation when Prometheus metrics are unavailable."""

    def mark_error(self) -> None:
        """No-op error marker."""

    def mark_success(self) -> None:
        """No-op success marker."""


@contextmanager
def _observe(operation: str) -> Iterator[DurationObservation | _NoopObservation]:
    """Yield a metrics observation, falling back to a no-op when metrics are disabled.

    Parameters
    ----------
    operation : str
        Operation name for metrics labeling.

    Yields
    ------
    DurationObservation | _NoopObservation
        Metrics observation when Prometheus is configured, otherwise a no-op recorder.
    """
    if not _METRICS_ENABLED:
        yield _NoopObservation()
        return
    try:
        with observe_duration(METRICS, operation, component=COMPONENT_NAME) as observation:
            yield observation
            return
    except ValueError:
        yield _NoopObservation()


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


def _semantic_search_sync(  # noqa: C901, PLR0915, PLR0914
    context: ApplicationContext,
    query: str,
    limit: int,
    session_id: str,
    scope: ScopeIn | None,
) -> AnswerEnvelope:
    start_time = perf_counter()
    with _observe("semantic_search") as observation:
        LOGGER.debug(
            "Semantic search with scope",
            extra={
                "session_id": session_id,
                "query": query,
                "has_scope": scope is not None,
                "scope_languages": scope.get("languages") if scope else None,  # type: ignore[typeddict-item]
                "scope_include_globs": scope.get("include_globs") if scope else None,  # type: ignore[typeddict-item]
            },
        )

        requested_limit = limit
        max_results = max(1, context.settings.limits.max_results)
        effective_limit = max(1, min(requested_limit, max_results))
        truncation_messages: list[str] = []
        if requested_limit <= 0:
            truncation_messages.append(
                f"Requested limit {requested_limit} is not positive; using minimum of 1."
            )
        if requested_limit > max_results:
            truncation_messages.append(
                f"Requested limit {requested_limit} exceeds max_results {max_results}; truncating to {max_results}."
            )

        ready, faiss_limits, faiss_error = context.ensure_faiss_ready()
        limits_metadata = [*faiss_limits, *truncation_messages]
        if not ready:
            observation.mark_error()
            raise VectorSearchError(
                faiss_error or "Semantic search not available - index not built",
                context={"faiss_index": str(context.paths.faiss_index)},
            )

        embedding, embed_error = _embed_query(context.vllm_client, query)
        if embedding is None or embed_error is not None:
            observation.mark_error()
            raise EmbeddingError(
                embed_error or "Embedding service unavailable",
                context={"vllm_url": context.settings.vllm.base_url},
            )

        has_include_globs = bool(scope and scope.get("include_globs"))
        has_exclude_globs = bool(scope and scope.get("exclude_globs"))
        has_languages = bool(scope and scope.get("languages"))
        has_scope_filters = has_include_globs or has_exclude_globs or has_languages

        multiplier = max(1, context.settings.limits.semantic_overfetch_multiplier)
        faiss_k_target = effective_limit
        if has_scope_filters:
            faiss_k_target = effective_limit * multiplier
            additional = 0
            if has_include_globs and has_languages:
                additional = effective_limit
            elif has_include_globs or has_languages:
                additional = max(1, effective_limit // 2)
            faiss_k_target += additional

        faiss_k = max(
            effective_limit,
            min(max_results, faiss_k_target),
        )
        if faiss_k < faiss_k_target:
            limits_metadata.append(
                f"FAISS fan-out clamped to {faiss_k} (max_results={max_results})."
            )

        LOGGER.debug(
            "Computed FAISS fan-out",
            extra={
                "requested_limit": requested_limit,
                "effective_limit": effective_limit,
                "faiss_k": faiss_k,
                "faiss_k_target": faiss_k_target,
                "multiplier": multiplier,
                "has_scope_filters": has_scope_filters,
                "has_include_globs": has_include_globs,
                "has_exclude_globs": has_exclude_globs,
                "has_languages": has_languages,
            },
        )

        result_ids, result_scores, search_exc = _run_faiss_search(
            context.faiss_manager,
            embedding,
            faiss_k,
            nprobe=context.settings.index.faiss_nprobe,
        )
        if search_exc is not None:
            observation.mark_error()
            raise VectorSearchError(
                str(search_exc),
                cause=search_exc,
                context={"faiss_index": str(context.paths.faiss_index)},
            )

        # Hydrate findings with scope filtering if scope has filters
        findings, hydrate_exc = _hydrate_findings(
            context,
            result_ids,
            result_scores,
            scope=scope,
        )
        if hydrate_exc is not None:
            observation.mark_error()
            raise VectorSearchError(
                str(hydrate_exc),
                cause=hydrate_exc,
                context={
                    "duckdb_path": str(context.paths.duckdb_path),
                    "vectors_dir": str(context.paths.vectors_dir),
                },
            )

        observation.mark_success()

        # Log warning if scope filtering reduced results significantly
        if scope and has_scope_filters and len(findings) < effective_limit:
            LOGGER.warning(
                "Scope filtering reduced results below requested limit",
                extra={
                    "requested_limit": effective_limit,
                    "actual_count": len(findings),
                    "faiss_results": len(result_ids),
                    "has_include_globs": has_include_globs,
                    "has_exclude_globs": has_exclude_globs,
                    "has_languages": has_languages,
                },
            )

        extras = _success_extras(
            limits_metadata, len(findings), requested_limit, effective_limit, start_time
        )
        # Include applied scope in response envelope
        if scope:
            extras["scope"] = scope

        return _make_envelope(
            findings=findings,
            answer=f"Found {len(findings)} semantically similar code chunks for: {query}",
            confidence=0.85 if findings else 0.0,
            extras=extras,
        )


def _embed_query(client: VLLMClient, query: str) -> tuple[np.ndarray | None, str | None]:
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

            include_globs = cast("list[str] | None", scope.get("include_globs")) if scope else None
            exclude_globs = cast("list[str] | None", scope.get("exclude_globs")) if scope else None
            languages = cast("list[str] | None", scope.get("languages")) if scope else None

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
            chunk_by_id = {int(record["id"]): record for record in records if "id" in record}

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
        "retrieval": ["semantic", "faiss"],
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
    findings_count: int,
    requested_limit: int,
    effective_limit: int,
    start_time: float,
) -> dict[str, object]:
    """Build a success extras payload with optional limits metadata.

    Parameters
    ----------
    limits : Sequence[str]
        Search limitations or warnings.
    findings_count : int
        Number of findings returned.
    requested_limit : int
        Requested result limit.
    effective_limit : int
        Effective limit applied after clamping.
    start_time : float
        Search start time (monotonic clock).

    Returns
    -------
    dict[str, object]
        Extras payload including method metadata and optional limits.
    """
    extras: dict[str, object] = {
        "method": _build_method(findings_count, requested_limit, effective_limit, start_time)
    }
    if limits:
        extras["limits"] = list(limits)
    return extras


__all__ = ["semantic_search"]
