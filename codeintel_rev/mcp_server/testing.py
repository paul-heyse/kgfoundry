"""Small in-process harness for exercising MCP tools without FastMCP."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from codeintel_rev.mcp_server.registry import McpDeps, call_tool, list_tools


@dataclass(slots=True)
class InProcessMCP:
    """Minimal harness for exercising MCP tools without FastMCP wiring."""

    deps: McpDeps

    def tools_list(self) -> list[dict[str, Any]]:
        """Return tool descriptors compatible with MCP /tools/list.

        Returns
        -------
        list[dict[str, Any]]
            Tool metadata records with JSON Schema payloads.
        """
        _ = self.deps
        return list_tools()

    def tools_call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool locally using the configured dependencies.

        Returns
        -------
        dict[str, Any]
            Response envelope compatible with MCP.
        """
        return call_tool(self.deps, name, arguments)
