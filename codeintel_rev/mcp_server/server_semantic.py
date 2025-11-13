"""Semantic MCP tool registrations (pure move from server.py)."""

from __future__ import annotations

import asyncio
from typing import Any

from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.mcp_server.adapters import deep_research as deep_research_adapter
from codeintel_rev.mcp_server.adapters import semantic as semantic_adapter
from codeintel_rev.mcp_server.adapters import semantic_pro as semantic_pro_adapter
from codeintel_rev.mcp_server.error_handling import handle_adapter_errors
from codeintel_rev.mcp_server.schemas import (
    AnswerEnvelope,
    FetchStructuredContent,
    FetchToolArgs,
    SearchFilterPayload,
    SearchStructuredContent,
    SearchToolArgs,
)
from codeintel_rev.mcp_server.server import get_context, mcp
from codeintel_rev.mcp_server.telemetry import tool_operation_scope
from codeintel_rev.telemetry.context import current_session
from codeintel_rev.telemetry.reporter import build_report as build_run_report
from codeintel_rev.telemetry.reporter import report_to_json


@mcp.tool(name="search")
@handle_adapter_errors(
    operation="search:deep",
    empty_result={"results": [], "queryEcho": "", "top_k": 0},
)
async def deep_research_search(
    query: str,
    top_k: int | None = None,
    filters: SearchFilterPayload | None = None,
    *,
    rerank: bool = True,
) -> SearchStructuredContent:
    """Deep-Research compatible semantic search that returns chunk ids.

    Returns
    -------
    SearchStructuredContent
        Structured MCP payload with ranked chunk identifiers and metadata.
    """
    context = get_context()
    args: SearchToolArgs = {"query": query}
    if top_k is not None:
        args["top_k"] = top_k
    if filters is not None:
        args["filters"] = filters
    if rerank is not None:
        args["rerank"] = rerank

    with tool_operation_scope(
        "search.deep",
        query_chars=len(query),
        requested_top_k=top_k or 12,
        rerank=rerank,
    ) as timeline:
        return await deep_research_adapter.search(context, timeline, args)


@mcp.tool(name="fetch")
@handle_adapter_errors(
    operation="search:fetch",
    empty_result={"objects": []},
)
async def deep_research_fetch(
    objectIds: list[str],  # noqa: N803 - MCP schema uses camelCase
    max_tokens: int | None = None,
) -> FetchStructuredContent:
    """Hydrate chunk ids produced by :func:`deep_research_search`.

    Returns
    -------
    FetchStructuredContent
        Structured MCP payload containing chunk contents and provenance metadata.
    """
    context = get_context()
    args: FetchToolArgs = {"objectIds": objectIds}
    if max_tokens is not None:
        args["max_tokens"] = max_tokens

    with tool_operation_scope(
        "search.fetch",
        requested_objects=len(objectIds),
        max_tokens=max_tokens or 4000,
    ) as timeline:
        return await deep_research_adapter.fetch(context, timeline, args)


@mcp.tool()
@handle_adapter_errors(
    operation="search:semantic",
    empty_result={"findings": [], "answer": "", "confidence": 0.0},
)
async def semantic_search(
    query: str,
    limit: int = 20,
) -> AnswerEnvelope:
    """Semantic code search using embeddings.

    Extended Summary
    ----------------
    This MCP tool performs semantic code search by embedding the query text,
    searching the FAISS vector index, and returning ranked code snippets with
    metadata. It uses the semantic adapter to execute the search pipeline and
    handles errors gracefully with structured error responses.

    Parameters
    ----------
    query : str
        Natural language query describing the code to find (e.g., "function that
        parses JSON files"). The query is embedded and used for vector similarity search.
    limit : int, optional
        Maximum number of results to return (default: 20). Higher limits improve
        recall but increase latency and response size.

    Returns
    -------
    AnswerEnvelope
        Structured semantic search response containing:
        - findings: list[Finding], ranked code snippets with metadata
        - answer: str, natural language summary of results
        - confidence: float, search confidence score (0.0-1.0)

    Notes
    -----
    This tool requires FAISS index and embedding service to be available. Search
    results are ranked by cosine similarity and include code snippets with location
    metadata. Time complexity: O(embedding_time + search_time) where search_time
    depends on index size and limit.
    """
    context = get_context()
    with tool_operation_scope(
        "search.semantic",
        query_chars=len(query),
        limit=limit,
    ):
        return await semantic_adapter.semantic_search(context, query, limit)


@mcp.tool()
@handle_adapter_errors(
    operation="search:semantic_pro",
    empty_result={"findings": [], "answer": "", "confidence": 0.0},
)
async def semantic_search_pro(
    query: str,
    limit: int = 20,
    *,
    options: semantic_pro_adapter.SemanticProOptions | None = None,
) -> AnswerEnvelope:
    """Two-stage semantic retrieval with optional late interaction and reranker.

    Extended Summary
    ----------------
    This MCP tool performs advanced semantic code search using a two-stage pipeline:
    CodeRank (hybrid BM25+SPLADE+FAISS) followed by optional WARP (late interaction)
    and optional LLM reranking. It provides fine-grained control over retrieval
    stages and reranking behavior through options. Used for high-precision code
    search when recall and ranking quality are critical.

    Parameters
    ----------
    query : str
        Natural language query describing the code to find. The query is used
        across all retrieval stages (BM25, SPLADE, FAISS, WARP, reranker).
    limit : int, optional
        Maximum number of results to return (default: 20). Applied after all
        stages and reranking.
    options : semantic_pro_adapter.SemanticProOptions | None, optional
        Optional configuration for retrieval stages:
        - use_coderank: bool, enable CodeRank hybrid search (default: True)
        - use_warp: bool, enable WARP late interaction (default: False)
        - use_reranker: bool, enable LLM reranking (default: False)
        - stage_weights: dict[str, float], custom fusion weights
        - explain: bool, include explanation in response
        - xtr_k: int, XTR reranker top-k
        - rerank: RerankOptionPayload, reranker configuration

    Returns
    -------
    AnswerEnvelope
        Structured semantic search response with findings, answer, and confidence.
        Results are ranked by the final stage (reranker if enabled, otherwise fusion).

    Notes
    -----
    This tool requires FAISS index, BM25 index, SPLADE index, and optionally WARP
    and reranker services. The two-stage pipeline improves recall and ranking quality
    at the cost of higher latency. Time complexity: O(stage1_time + stage2_time + rerank_time).
    """
    context = get_context()
    with tool_operation_scope(
        "search.semantic_pro",
        query_chars=len(query),
        limit=limit,
    ):
        return await semantic_pro_adapter.semantic_search_pro(
            context,
            query=query,
            limit=limit,
            options=options,
        )


@mcp.tool()
async def telemetry_run_report(
    session_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Return the latest run report for the active or requested session.

    Parameters
    ----------
    session_id : str | None
        Optional explicit session identifier. Defaults to the current request session.
    run_id : str | None
        Optional run identifier when multiple runs exist for a session.

    Returns
    -------
    dict[str, Any]
        JSON-safe run report payload.

    Raises
    ------
    RuntimeError
        Raised when no session identifier can be resolved.
    """
    context = get_context()
    effective_session = session_id or current_session()
    if effective_session is None:
        msg = "Session ID unavailable; pass session_id explicitly."
        raise RuntimeError(msg)
    return await asyncio.to_thread(_render_run_report, context, effective_session, run_id)


def _render_run_report(
    context: ApplicationContext,
    session_id: str,
    run_id: str | None,
) -> dict[str, Any]:
    report = build_run_report(context, session_id, run_id)
    if report is None:
        return {
            "session_id": session_id,
            "error": "run_not_found",
        }
    return report_to_json(report)
