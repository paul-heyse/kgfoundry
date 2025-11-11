"""Semantic MCP tool registrations (pure move from server.py)."""

from __future__ import annotations

from codeintel_rev.mcp_server.adapters import semantic as semantic_adapter
from codeintel_rev.mcp_server.adapters import semantic_pro as semantic_pro_adapter
from codeintel_rev.mcp_server.error_handling import handle_adapter_errors
from codeintel_rev.mcp_server.schemas import AnswerEnvelope
from codeintel_rev.mcp_server.server import get_context, mcp
from codeintel_rev.mcp_server.telemetry import tool_operation_scope


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

    Returns
    -------
    AnswerEnvelope
        Structured semantic search response.
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

    Returns
    -------
    AnswerEnvelope
        Structured response including fusion metadata.
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
