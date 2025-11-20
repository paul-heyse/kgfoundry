"""Tests for MCP registry contracts: tool calling and response formatting."""

from __future__ import annotations

from typing import Any

from codeintel_rev.mcp_server.registry import McpDeps, call_tool

from tests._helpers import assertions


class _StubCatalog:
    """Stub catalog for testing MCP registry contracts."""

    def __init__(self) -> None:
        """Initialize stub catalog with test rows."""
        self.rows = [
            {
                "id": 1,
                "uri": "repo://file.py",
                "start_line": 0,
                "end_line": 4,
                "preview": "def foo():\n    return 1",
                "content": "def foo():\n    return 1",
                "lang": "python",
            }
        ]

    def query_by_ids(self, ids: list[int]) -> list[dict[str, Any]]:
        """Query rows by chunk IDs.

        Parameters
        ----------
        ids : list[int]
            Chunk IDs to look up.

        Returns
        -------
        list[dict[str, Any]]
            Matching rows from internal storage.
        """
        return [row for row in self.rows if row["id"] in ids]


def _faiss_search(query: str, top_k: int) -> list[tuple[int, float]]:
    """Perform stub FAISS search.

    Parameters
    ----------
    query : str
        Query string (must be non-empty).
    top_k : int
        Number of results (ignored).

    Returns
    -------
    list[tuple[int, float]]
        Stub search results [(1, 0.9)].
    """
    _ = top_k
    assertions.expect_true(bool(query), reason="query should be non-empty")
    return [(1, 0.9)]


def test_call_tool_includes_summary_for_search() -> None:
    """Test that call_tool includes summary and structured content for search operations."""
    deps = McpDeps(catalog=_StubCatalog(), faiss_search=_faiss_search)
    response = call_tool(deps, "search", {"query": "foo", "top_k": 1})
    assertions.expect_in("content", response)
    summary = response["content"][0]["text"]
    assertions.expect_in("search returned", summary)
    assertions.expect_in("structuredContent", response)


def test_call_tool_includes_summary_for_fetch() -> None:
    """Test that call_tool includes summary and structured content for fetch operations."""
    deps = McpDeps(catalog=_StubCatalog())
    response = call_tool(deps, "fetch", {"objectIds": ["1"]})
    assertions.expect_in("content", response)
    summary = response["content"][0]["text"]
    assertions.expect_in("fetch returned", summary)
    assertions.expect_in("structuredContent", response)
