from __future__ import annotations

from typing import Any

from codeintel_rev.mcp_server.registry import McpDeps, call_tool


class _StubCatalog:
    def __init__(self) -> None:
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
        return [row for row in self.rows if row["id"] in ids]


def _faiss_search(query: str, top_k: int) -> list[tuple[int, float]]:
    _ = top_k
    assert query
    return [(1, 0.9)]


def test_call_tool_includes_summary_for_search() -> None:
    deps = McpDeps(catalog=_StubCatalog(), faiss_search=_faiss_search)
    response = call_tool(deps, "search", {"query": "foo", "top_k": 1})
    assert "content" in response
    summary = response["content"][0]["text"]
    assert "search returned" in summary
    assert "structuredContent" in response


def test_call_tool_includes_summary_for_fetch() -> None:
    deps = McpDeps(catalog=_StubCatalog())
    response = call_tool(deps, "fetch", {"objectIds": ["1"]})
    assert "content" in response
    summary = response["content"][0]["text"]
    assert "fetch returned" in summary
    assert "structuredContent" in response
