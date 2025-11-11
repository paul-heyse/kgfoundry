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
