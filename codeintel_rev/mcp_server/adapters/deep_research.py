"""Adapters that expose MCP Deep-Research search/fetch semantics."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.mcp_server.schemas import (
    FetchObject,
    FetchObjectMetadata,
    FetchStructuredContent,
    FetchToolArgs,
    SearchResultItem,
    SearchResultMetadata,
    SearchStructuredContent,
    SearchToolArgs,
)
from codeintel_rev.observability.timeline import Timeline
from codeintel_rev.retrieval.mcp_search import (
    FetchDependencies,
    FetchRequest,
    FetchResponse,
    SearchDependencies,
    SearchFilters,
    SearchRequest,
    SearchResponse,
    run_fetch,
    run_search,
)
from kgfoundry_common.errors import VectorSearchError
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)
_TRACE_SUBDIR = Path("trace/mcp_pool")


def _pool_dir(data_dir: Path) -> Path:
    return data_dir / _TRACE_SUBDIR


def _clamp_top_k(raw: int | None) -> int:
    value = raw if raw is not None else 12
    return max(1, min(50, int(value)))


def _clamp_max_tokens(raw: int | None) -> int:
    value = raw if raw is not None else 4000
    return max(256, min(16000, int(value)))


def _serialize_search_response(response: SearchResponse) -> SearchStructuredContent:
    """Convert an internal search response into MCP structured content.

    This function transforms a SearchResponse dataclass (containing search results
    from the retrieval pipeline) into a SearchStructuredContent TypedDict suitable
    for JSON serialization and transmission via the MCP protocol. The function
    extracts chunk metadata (IDs, titles, URLs, snippets, scores) and formats
    them according to the MCP schema.

    Parameters
    ----------
    response : SearchResponse
        Internal search response containing ranked results, query echo, top_k,
        and optional limits. The response.results list contains SearchResult
        objects with chunk metadata and scores.

    Returns
    -------
    SearchStructuredContent
        JSON-safe payload returned to the MCP transport. Contains a list of
        SearchResultItem objects with id, title, url, snippet, score, source,
        and metadata fields. Also includes queryEcho, top_k, and optional
        limits array.
    """
    results: list[SearchResultItem] = [
        SearchResultItem(
            id=str(result.chunk_id),
            title=result.title,
            url=result.url,
            snippet=result.snippet,
            score=result.score,
            source=result.source,
            metadata=cast("SearchResultMetadata", result.metadata),
        )
        for result in response.results
    ]
    payload = SearchStructuredContent(
        results=results,
        queryEcho=response.query_echo,
        top_k=response.top_k,
    )
    if response.limits:
        payload["limits"] = list(response.limits)
    return payload


def _serialize_fetch_response(response: FetchResponse) -> FetchStructuredContent:
    """Convert an internal fetch response into MCP structured content.

    This function transforms a FetchResponse dataclass (containing hydrated chunk
    objects from the catalog) into a FetchStructuredContent TypedDict suitable for
    JSON serialization and transmission via the MCP protocol. The function extracts
    chunk content and metadata (IDs, titles, URLs, content, metadata) and formats
    them according to the MCP schema.

    Parameters
    ----------
    response : FetchResponse
        Internal fetch response containing hydrated chunk objects. The response.objects
        list contains FetchObjectResult objects with full chunk content and metadata.

    Returns
    -------
    FetchStructuredContent
        JSON-safe payload containing hydrated chunk objects. Contains a list of
        FetchObject objects with id, title, url, content, and metadata fields.
        The content field contains the full text of the chunk.
    """
    objects: list[FetchObject] = [
        FetchObject(
            id=str(obj.chunk_id),
            title=obj.title,
            url=obj.url,
            content=obj.content,
            metadata=cast("FetchObjectMetadata", obj.metadata),
        )
        for obj in response.objects
    ]
    return FetchStructuredContent(objects=objects)


async def search(
    context: ApplicationContext,
    timeline: Timeline,
    payload: SearchToolArgs,
) -> SearchStructuredContent:
    """Execute the Deep-Research search pipeline.

    This async function orchestrates the complete search workflow: validates
    FAISS index availability, normalizes search filters, constructs search
    requests, executes FAISS search with optional reranking, and serializes
    results for MCP transport. The function runs the search operation in a
    thread pool to avoid blocking the async event loop.

    Parameters
    ----------
    context : ApplicationContext
        Application context providing access to FAISS manager, catalog, embedding
        client, settings, and data directories. Used to construct search dependencies
        and validate index availability.
    timeline : Timeline
        Timeline instance for recording search events and observability. Used to
        track search operations and provide session/run IDs for telemetry.
    payload : SearchToolArgs
        MCP search tool arguments containing query text, optional top_k, rerank
        flag, and optional filters (languages, include/exclude paths, symbols).
        The payload is validated and normalized before constructing SearchRequest.

    Returns
    -------
    SearchStructuredContent
        Structured MCP payload containing ranked chunk results with metadata
        (IDs, titles, URLs, snippets, scores). Results are ranked by relevance
        score and filtered according to the provided filters.

    Raises
    ------
    VectorSearchError
        Raised when the FAISS index cannot be loaded or is unavailable. The error
        includes context about the index path for debugging.
    """
    ready, limits, error = context.ensure_faiss_ready()
    if not ready:
        raise VectorSearchError(
            error or "FAISS index unavailable",
            context={"faiss_index": str(context.paths.faiss_index)},
        )
    raw_filters = payload.get("filters")
    normalized_filters: Mapping[str, Sequence[str]] | None = (
        cast("Mapping[str, Sequence[str]]", raw_filters) if raw_filters else None
    )
    filters = SearchFilters.from_payload(normalized_filters)
    request = SearchRequest(
        query=str(payload["query"]),
        top_k=_clamp_top_k(payload.get("top_k")),
        rerank=bool(payload.get("rerank", True)),
        filters=filters,
    )

    def _work() -> SearchStructuredContent:
        with context.open_catalog() as catalog:
            deps = SearchDependencies(
                faiss=context.faiss_manager,
                embedder=context.vllm_client,
                catalog=catalog,
                settings=context.settings,
                session_id=timeline.session_id,
                run_id=timeline.run_id,
                limits=limits,
                pool_dir=_pool_dir(context.paths.data_dir),
                timeline=timeline,
            )
            response = run_search(request=request, deps=deps)
            return _serialize_search_response(response)

    return await asyncio.to_thread(_work)


async def fetch(
    context: ApplicationContext,
    timeline: Timeline,
    payload: FetchToolArgs,
) -> FetchStructuredContent:
    """Hydrate chunk ids returned from the MCP search tool.

    This async function retrieves full chunk content and metadata for a list of
    chunk IDs returned from a previous search operation. The function normalizes
    object IDs, constructs fetch requests, queries the DuckDB catalog, and
    serializes hydrated chunks for MCP transport. The function runs the fetch
    operation in a thread pool to avoid blocking the async event loop.

    Parameters
    ----------
    context : ApplicationContext
        Application context providing access to DuckDB catalog, settings, and
        data directories. Used to construct fetch dependencies and open catalog
        connections.
    timeline : Timeline
        Timeline instance for recording fetch events and observability. Used to
        track fetch operations and provide session/run IDs for telemetry.
    payload : FetchToolArgs
        MCP fetch tool arguments containing objectIds (list of chunk ID strings)
        and optional max_tokens limit. The objectIds are normalized to integers
        and validated before querying the catalog.

    Returns
    -------
    FetchStructuredContent
        Structured MCP payload containing hydrated chunk objects with full content
        and metadata (IDs, titles, URLs, content, metadata). Chunks are returned
        in the order specified by objectIds, with missing chunks omitted.
    """
    object_ids = _normalize_object_ids(payload["objectIds"])
    request = FetchRequest(
        object_ids=object_ids,
        max_tokens=_clamp_max_tokens(payload.get("max_tokens")),
    )

    def _work() -> FetchStructuredContent:
        with context.open_catalog() as catalog:
            deps = FetchDependencies(
                catalog=catalog,
                settings=context.settings,
                timeline=timeline,
            )
            response = run_fetch(request=request, deps=deps)
            return _serialize_fetch_response(response)

    return await asyncio.to_thread(_work)


def _normalize_object_ids(raw_ids: Sequence[str]) -> tuple[int, ...]:
    """Normalize object identifiers while preserving ordering.

    This helper function converts a sequence of string chunk IDs to a tuple of
    integers, preserving the original order. Used to normalize MCP fetch payload
    objectIds before querying the catalog. Invalid IDs (non-numeric strings)
    raise ValueError during conversion.

    Parameters
    ----------
    raw_ids : Sequence[str]
        Sequence of chunk ID strings to normalize. Each string should represent
        a valid integer chunk ID. Empty sequences return an empty tuple.

    Returns
    -------
    tuple[int, ...]
        Tuple of normalized integer chunk IDs preserving the incoming order.
        The tuple has the same length as raw_ids (unless conversion fails).

    Notes
    -----
    This function is used by fetch() to normalize MCP payload objectIds before
    constructing FetchRequest. Time complexity: O(n) where n is the length of
    raw_ids. The function is deterministic and preserves order.
    """
    return tuple(int(raw) for raw in raw_ids)


__all__ = ["fetch", "search"]
