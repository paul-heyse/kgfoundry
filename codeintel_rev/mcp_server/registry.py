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
    fetch_input_schema,
    fetch_output_schema,
    search_input_schema,
    search_output_schema,
)


@dataclass(slots=True)
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

    Returns
    -------
    dict[str, Any]
        MCP-compatible response envelope.
    """
    if name == "search":
        out = handle_search(
            SearchDeps(
                catalog=deps.catalog,
                faiss_search=deps.faiss_search,
                sparse_search=deps.sparse_search,
            ),
            arguments or {},
        )
        return {"structuredContent": msgspec.to_builtins(out)}
    if name == "fetch":
        out: FetchOutput = handle_fetch(deps.catalog, arguments or {})
        return {"structuredContent": msgspec.to_builtins(out)}
    return {
        "isError": True,
        "content": [
            {"type": "text", "text": f"Unknown tool: {name}"},
        ],
    }
