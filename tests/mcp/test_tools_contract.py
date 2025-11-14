from __future__ import annotations

from collections.abc import Sequence

from codeintel_rev.mcp_server.registry import McpDeps
from codeintel_rev.mcp_server.testing import InProcessMCP


class _CatalogStub:
    def __init__(self) -> None:
        self._rows: dict[int, dict[str, object]] = {
            1: {
                "id": 1,
                "uri": "pkg/a.py",
                "start_line": 0,
                "end_line": 4,
                "lang": "python",
                "content": "def foo():\n    return 1",
                "preview": "def foo():\n    return 1",
            },
            2: {
                "id": 2,
                "uri": "pkg/b.py",
                "start_line": 10,
                "end_line": 14,
                "lang": "python",
                "content": "def bar():\n    return 2",
                "preview": "def bar():\n    return 2",
            },
        }

    def query_by_ids(self, ids: Sequence[int]) -> list[dict[str, object]]:
        return [self._rows[i] for i in ids if i in self._rows]


def test_tools_list_contract() -> None:
    harness = InProcessMCP(McpDeps(catalog=_CatalogStub()))
    tools = harness.tools_list()
    names = {tool["name"] for tool in tools}
    assert {"search", "fetch"}.issubset(names)
    assert tools[0]["inputSchema"]["type"] == "object"
    assert tools[1]["inputSchema"]["properties"]["objectIds"]["type"] == "array"


def test_search_fetch_roundtrip() -> None:
    catalog = _CatalogStub()
    harness = InProcessMCP(
        McpDeps(
            catalog=catalog,
            faiss_search=lambda _q, _k: [(1, 0.95), (2, 0.9)],
        )
    )
    search = harness.tools_call("search", {"query": "add numbers", "top_k": 2})
    results = search["structuredContent"]["results"]
    assert len(results) == 2
    first_id = results[0]["id"]
    fetch = harness.tools_call("fetch", {"objectIds": [first_id], "max_tokens": 512})
    objects = fetch["structuredContent"]["objects"]
    assert len(objects) == 1
    assert objects[0]["id"] == first_id
    assert "def" in objects[0]["content"]
