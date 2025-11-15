"""Semantic MCP tool registrations (pure move from server.py)."""

from __future__ import annotations

from typing import Any

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


@mcp.tool(name="search")
@handle_adapter_errors(
    operation="search:deep",
    empty_result={"results": [], "queryEcho": "", "top_k": 0, "limits": []},
)
async def deep_research_search(
    query: str,
    top_k: int | None = None,
    filters: SearchFilterPayload | None = None,
    *,
    rerank: bool = True,
) -> SearchStructuredContent:
    """Deep-Research compatible semantic search that returns chunk ids.

    This async function provides a Deep-Research compatible search interface that
    executes semantic search using FAISS and returns ranked chunk identifiers with
    metadata. The function constructs MCP tool arguments, creates a timeline for
    observability, and delegates to the deep_research adapter for execution.

    Parameters
    ----------
    query : str
        Search query text. Used to perform semantic similarity search over the
        indexed codebase. The query is embedded and searched against FAISS vectors.
    top_k : int | None, optional
        Maximum number of results to return (default: None). When None, uses the
        default top_k value (12). The value is clamped to the range [1, 50] before
        execution. Higher values return more results but increase latency.
    filters : SearchFilterPayload | None, optional
        Optional search filters for narrowing results by language, file paths,
        or symbols (default: None). When None, no filtering is applied. Filters
        are normalized and applied during post-search hydration.
    rerank : bool, optional
        Whether to enable exact reranking of candidates (default: True). When True,
        candidates are reranked using exact similarity scores. When False, uses
        approximate search results only.

    Returns
    -------
    SearchStructuredContent
        Structured MCP payload with ranked chunk identifiers and metadata. Contains
        SearchResultItem objects with id, title, url, snippet, score, source, and
        metadata fields. Results are ranked by relevance score.
    """
    context = get_context()
    args: SearchToolArgs = {"query": query}
    if top_k is not None:
        args["top_k"] = top_k
    if filters is not None:
        args["filters"] = filters
    if rerank is not None:
        args["rerank"] = rerank

    return await deep_research_adapter.search(context, args)


@mcp.tool(name="fetch")
@handle_adapter_errors(
    operation="search:fetch",
    empty_result={"objects": []},
)
async def deep_research_fetch(
    objectIds: list[str],  # lint-ignore[N803]: MCP schema uses camelCase
    max_tokens: int | None = None,
) -> FetchStructuredContent:
    """Hydrate chunk ids produced by :func:`deep_research_search`.

    This async function retrieves full chunk content and metadata for chunk IDs
    returned from a previous search operation. The function constructs MCP tool
    arguments, creates a timeline for observability, and delegates to the deep_research
    adapter for execution.

    Parameters
    ----------
    objectIds : list[str]
        List of chunk ID strings to hydrate. IDs are normalized to integers and
        queried from the DuckDB catalog. Missing chunks are omitted from results.
        Must be non-empty for meaningful results.
    max_tokens : int | None, optional
        Maximum token limit for chunk content (default: None). When None, uses the
        default max_tokens value (4000). The value is clamped to the range [256, 16000]
        before execution. Used to limit response size and control token usage.

    Returns
    -------
    FetchStructuredContent
        Structured MCP payload containing chunk contents and provenance metadata.
        Contains FetchObject objects with id, title, url, content, and metadata
        fields. Chunks are returned in the order specified by objectIds.
    """
    context = get_context()
    args: FetchToolArgs = {"objectIds": objectIds}
    if max_tokens is not None:
        args["max_tokens"] = max_tokens

    return await deep_research_adapter.fetch(context, args)


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
    """Return placeholder data because legacy run reports have been removed.

    Parameters
    ----------
    session_id : str | None, optional
        Session identifier (unused, kept for API compatibility). Defaults to None.
    run_id : str | None, optional
        Run identifier (unused, kept for API compatibility). Defaults to None.

    Returns
    -------
    dict[str, Any]
        Dictionary with "error" key set to "run_reports_unavailable", indicating
        that legacy run reports are no longer available.
    """
    _ = (session_id, run_id)
    return {"error": "run_reports_unavailable"}
