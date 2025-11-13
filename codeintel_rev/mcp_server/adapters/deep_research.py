"""Adapters that expose MCP Deep-Research search/fetch semantics."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.mcp_server.schemas import (
    FetchStructuredContent,
    FetchToolArgs,
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

    Returns
    -------
    SearchStructuredContent
        JSON-safe payload returned to FastMCP.
    """
    payload: SearchStructuredContent = {
        "results": [
            {
                "id": str(result.chunk_id),
                "title": result.title,
                "url": result.url,
                "snippet": result.snippet,
                "score": result.score,
                "source": result.source,
                "metadata": result.metadata,
            }
            for result in response.results
        ],
        "queryEcho": response.query_echo,
        "top_k": response.top_k,
    }
    if response.limits:
        payload["limits"] = list(response.limits)
    return payload


def _serialize_fetch_response(response: FetchResponse) -> FetchStructuredContent:
    """Convert an internal fetch response into MCP structured content.

    Returns
    -------
    FetchStructuredContent
        JSON-safe payload returned to FastMCP.
    """
    return {
        "objects": [
            {
                "id": str(obj.chunk_id),
                "title": obj.title,
                "url": obj.url,
                "content": obj.content,
                "metadata": obj.metadata,
            }
            for obj in response.objects
        ]
    }


async def search(
    context: ApplicationContext,
    timeline: Timeline,
    payload: SearchToolArgs,
) -> SearchStructuredContent:
    """Execute the Deep-Research search pipeline.

    Returns
    -------
    SearchStructuredContent
        Structured MCP payload containing ranked chunk ids.

    Raises
    ------
    VectorSearchError
        Raised when the FAISS index cannot be loaded.
    """
    ready, limits, error = context.ensure_faiss_ready()
    if not ready:
        raise VectorSearchError(
            error or "FAISS index unavailable",
            context={"faiss_index": str(context.paths.faiss_index)},
        )
    filters = SearchFilters.from_payload(payload.get("filters"))
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

    Returns
    -------
    FetchStructuredContent
        Structured MCP payload containing hydrated chunk contents.
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

    Returns
    -------
    tuple[int, ...]
        Normalised identifiers preserving the incoming order.
    """
    return tuple(int(raw) for raw in raw_ids)


__all__ = ["fetch", "search"]
