"""In-process registry for the lightweight MCP testing harness."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import msgspec

from codeintel_rev.mcp_server.fetch_tool import handle_fetch
from codeintel_rev.mcp_server.search_tool import SearchDeps, handle_search
from codeintel_rev.mcp_server.types import (
    FetchOutput,
    SearchOutput,
    fetch_input_schema,
    fetch_output_schema,
    search_input_schema,
    search_output_schema,
)


@dataclass(slots=True, frozen=True)
class McpDeps:
    """Dependencies required for running the lightweight MCP tools."""

    catalog: Any
    faiss_search: Callable[[str, int], list[tuple[int, float]]] | None = None
    sparse_search: Callable[[str, int], list[tuple[int, float]]] | None = None


def list_tools() -> list[dict[str, Any]]:
    """Return tool metadata compatible with MCP /tools/list responses.

    Returns
    -------
    list[dict[str, Any]]
        Tool descriptor records with JSON Schemas for search and fetch.
    """
    return [
        {
            "name": "search",
            "description": "Search code chunks and return IDs with snippets.",
            "inputSchema": search_input_schema(),
            "outputSchema": search_output_schema(),
        },
        {
            "name": "fetch",
            "description": "Fetch hydrated chunk content for previously returned IDs.",
            "inputSchema": fetch_input_schema(),
            "outputSchema": fetch_output_schema(),
        },
    ]


def call_tool(deps: McpDeps, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute a tool using the provided dependencies.

    This function dispatches tool execution requests to the appropriate handler
    (search or fetch) and packages the response in MCP-compatible format. It is
    called by MCP server implementations to execute tools requested by clients.

    Parameters
    ----------
    deps : McpDeps
        MCP dependencies including catalog and search functions.
    name : str
        Tool name to execute, typically "search" or "fetch".
    arguments : dict[str, Any]
        Tool-specific arguments dictionary passed to the handler.

    Returns
    -------
    dict[str, Any]
        MCP-compatible response envelope containing structuredContent for successful
        tool execution, or isError flag with error content for unknown tools.
    """
    if name == "search":
        try:
            search_out = handle_search(
                SearchDeps(
                    catalog=deps.catalog,
                    faiss_search=deps.faiss_search,
                    sparse_search=deps.sparse_search,
                ),
                arguments or {},
            )
        except ValueError as exc:
            return _error_response(str(exc))
        summary = (
            f"search returned {len(search_out.results)} results "
            f"for '{search_out.queryEcho}'"
        )
        return _success_response(summary, search_out)
    if name == "fetch":
        try:
            fetch_out: FetchOutput = handle_fetch(deps.catalog, arguments or {})
        except ValueError as exc:
            return _error_response(str(exc))
        summary = f"fetch returned {len(fetch_out.objects)} objects"
        return _success_response(summary, fetch_out)
    return _error_response(f"Unknown tool: {name}")


def _error_response(message: str) -> dict[str, Any]:
    """Build an MCP-compatible error response envelope.

    Parameters
    ----------
    message : str
        Error message to include in the response.

    Returns
    -------
    dict[str, Any]
        MCP error response dictionary with isError flag and content array.
    """
    return {
        "isError": True,
        "content": [
            {"type": "text", "text": message},
        ],
    }


def _success_response(summary: str, payload: SearchOutput | FetchOutput) -> dict[str, Any]:
    """Return MCP-compatible success payload with summary text and structured content.

    Parameters
    ----------
    summary : str
        Human-readable summary describing the tool result.
    payload : SearchOutput | FetchOutput
        Structured response payload emitted by the tool handler.

    Returns
    -------
    dict[str, Any]
        Envelope containing a text summary and structuredContent ready for MCP clients.
    """
    structured = msgspec.to_builtins(payload)
    return {
        "content": [
            {
                "type": "text",
                "text": summary,
            }
        ],
        "structuredContent": structured,
    }
