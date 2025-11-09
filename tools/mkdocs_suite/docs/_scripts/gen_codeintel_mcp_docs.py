"""Generate CodeIntel MCP tools documentation from server schemas."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, TypedDict, cast

try:
    from codeintel.mcp_server.server import MCPServer  # type: ignore[reportMissingImports]
except ImportError:
    # codeintel package not available - this script is for generating docs when it exists
    MCPServer = None

HEADER = """# CodeIntel MCP Tools

Auto-generated from server schemas. Do not edit manually.

"""

LOGGER = logging.getLogger(__name__)


class ToolSchema(TypedDict, total=False):
    """Typed representation of an MCP tool schema."""

    name: str
    description: str
    inputSchema: dict[str, Any]


def main() -> None:
    """Generate tools.md from MCPServer tool schemas."""
    if MCPServer is None:
        LOGGER.warning("codeintel package not available, skipping doc generation")
        return
    tools_list = cast("list[ToolSchema]", MCPServer.tool_schemas())
    lines = [HEADER]
    for tool in tools_list:
        name = tool.get("name")
        if not isinstance(name, str):
            LOGGER.warning("Skipping tool entry without a name", extra={"entry": tool})
            continue
        description_value = tool.get("description", "")
        description = description_value if isinstance(description_value, str) else ""
        lines.append(f"## `{name}`\n\n{description}\n")
        schema = tool.get("inputSchema") or {}
        if not isinstance(schema, dict):
            LOGGER.warning(
                "Skipping schema for tool because inputSchema is not a mapping",
                extra={"tool": name},
            )
            schema = {}
        props = schema.get("properties", {})
        if not isinstance(props, dict):
            props = {}

        required_raw = schema.get("required", [])
        req = {str(item) for item in required_raw} if isinstance(required_raw, list) else set()
        if props:
            lines.append("**Parameters**:\n")
            for key, value in props.items():
                if not isinstance(key, str):
                    continue
                if isinstance(value, dict):
                    typ = str(value.get("type", "any"))
                    desc = str(value.get("description", ""))
                else:
                    typ = "any"
                    desc = str(value)
                star = " *(required)*" if key in req else ""
                lines.append(f"- `{key}`: `{typ}`{star} — {desc}")
            lines.append("\n")
        else:
            lines.append("**Parameters**: None\n\n")
    output_path = (
        Path(__file__).resolve().parents[3] / "docs" / "modules" / "codeintel" / "tools.md"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    LOGGER.info("Generated CodeIntel MCP docs", extra={"output_path": str(output_path)})


if __name__ == "__main__":
    main()
