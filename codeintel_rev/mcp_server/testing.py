"""Small in-process harness for exercising MCP tools without FastMCP."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from codeintel_rev.mcp_server.registry import McpDeps, call_tool, list_tools


@dataclass(slots=True, frozen=True)
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

        This method dispatches tool execution requests to the call_tool function
        using the instance's configured dependencies. It is used by in-process MCP
        implementations for testing and local tool execution without network overhead.

        Parameters
        ----------
        name : str
            Tool name to execute, typically "search" or "fetch".
        arguments : dict[str, Any]
            Tool-specific arguments dictionary passed to the handler.

        Returns
        -------
        dict[str, Any]
            Response envelope compatible with MCP containing structuredContent
            for successful tool execution, or isError flag with error content.
        """
        return call_tool(self.deps, name, arguments)
