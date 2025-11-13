from __future__ import annotations

import asyncio
import importlib
from collections.abc import Mapping
from typing import Any

from codeintel_rev.mcp_server.server import mcp

_ = importlib.import_module("codeintel_rev.mcp_server.server_semantic")


def test_tools_list_includes_search_and_fetch() -> None:
    async def _collect() -> Mapping[str, Any]:
        return await mcp.get_tools()

    tools: Mapping[str, Any] = asyncio.run(_collect())
    assert "search" in tools
    assert "fetch" in tools

    search_tool = tools["search"]
    fetch_tool = tools["fetch"]
    search_schema = search_tool.parameters
    fetch_schema = fetch_tool.parameters

    assert search_schema["properties"]["query"]["type"] == "string"
    assert "objectIds" in fetch_schema["properties"]
