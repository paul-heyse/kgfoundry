"""Tests for MCP tools list functionality."""

from __future__ import annotations

import asyncio
import importlib
from collections.abc import Mapping
from typing import Any

from codeintel_rev.mcp_server.server import mcp

from tests._helpers import assertions

_ = importlib.import_module("codeintel_rev.mcp_server.server_semantic")


def test_tools_list_includes_search_and_fetch() -> None:
    """Verify tools_list includes search and fetch tools with correct schemas."""

    async def _collect() -> Mapping[str, Any]:
        """Collect tools from MCP server.

        Returns
        -------
        Mapping[str, Any]
            Dictionary of tool names to tool definitions.
        """
        return await mcp.get_tools()

    tools: Mapping[str, Any] = asyncio.run(_collect())
    assertions.expect_in("search", tools)
    assertions.expect_in("fetch", tools)

    search_tool = tools["search"]
    fetch_tool = tools["fetch"]
    search_schema = search_tool.parameters
    fetch_schema = fetch_tool.parameters

    assertions.expect_equal(search_schema["properties"]["query"]["type"], "string")
    assertions.expect_in("object_ids", fetch_schema["properties"])
