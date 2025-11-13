from __future__ import annotations

import asyncio

import codeintel_rev.mcp_server.server_semantic  # noqa: F401 - ensures tool registration
from codeintel_rev.mcp_server.server import mcp


def test_tools_list_includes_search_and_fetch() -> None:
    async def _collect() -> dict[str, object]:
        return await mcp.get_tools()

    tools = asyncio.run(_collect())
    assert "search" in tools
    assert "fetch" in tools

    search_schema = tools["search"].parameters
    fetch_schema = tools["fetch"].parameters

    assert search_schema["properties"]["query"]["type"] == "string"
    assert "objectIds" in fetch_schema["properties"]
