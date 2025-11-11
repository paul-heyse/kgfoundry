"""Generate CodeIntel MCP tools documentation from live server schemas."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, TypedDict, cast

try:
    from codeintel_rev.mcp_server import server as mcp_server
except ImportError as exc:  # pragma: no cover - optional dependency guard
    mcp_server = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None

HEADER = """# CodeIntel MCP Tools

Auto-generated from server schemas. Do not edit manually.

"""

LOGGER = logging.getLogger(__name__)


class ToolSchema(TypedDict, total=False):
    """Typed representation of an MCP tool schema."""

    name: str
    description: str
    inputSchema: dict[str, Any]


async def _collect_tool_schemas() -> list[ToolSchema]:
    """Return normalized tool schemas from the FastMCP instance.

    Returns
    -------
    list[ToolSchema]
        Tool metadata including JSON Schemas for each input payload.
    """
    if mcp_server is None or IMPORT_ERROR is not None:
        LOGGER.warning(
            "codeintel_rev.mcp_server unavailable; skipping tool doc generation",
            extra={"error": repr(IMPORT_ERROR)},
        )
        return []

    tools = await mcp_server.mcp.get_tools()
    schemas: list[ToolSchema] = []
    for name, tool in sorted(tools.items()):
        parameters = getattr(tool, "parameters", {})
        schema = parameters if isinstance(parameters, dict) else {}
        description = tool.description or ""
        schemas.append(
            {
                "name": name,
                "description": description,
                "inputSchema": cast("dict[str, Any]", schema),
            }
        )
    return schemas


def _render_tool_entry(tool: ToolSchema) -> list[str]:
    """Render a single tool entry as Markdown lines.

    Parameters
    ----------
    tool : ToolSchema
        Tool metadata containing description and JSON schema.

    Returns
    -------
    list[str]
        Markdown lines describing the tool.
    """
    name = tool.get("name") or ""
    description = tool.get("description") or ""
    lines = [f"## `{name}`\n\n{description}\n"]
    schema = tool.get("inputSchema") or {}
    props = schema.get("properties") if isinstance(schema, dict) else {}
    if not isinstance(props, dict) or not props:
        lines.append("**Parameters**: None\n\n")
        return lines

    required_raw = schema.get("required") if isinstance(schema, dict) else []
    required = {str(item) for item in required_raw} if isinstance(required_raw, list) else set()
    lines.append("**Parameters**:\n")
    for key, value in sorted(props.items()):
        if not isinstance(key, str):
            continue
        if isinstance(value, dict):
            typ = str(value.get("type", "any"))
            desc = str(value.get("description", ""))
        else:
            typ = "any"
            desc = str(value)
        star = " *(required)*" if key in required else ""
        lines.append(f"- `{key}`: `{typ}`{star} — {desc}")
    lines.append("\n")
    return lines


def main() -> None:
    """Generate tools.md from the live CodeIntel MCP server."""
    tools = asyncio.run(_collect_tool_schemas())
    if not tools:
        LOGGER.warning("No tool schemas discovered; aborting generation")
        return

    lines = [HEADER]
    for tool in tools:
        name = tool.get("name")
        if not name:
            LOGGER.warning("Skipping unnamed tool entry", extra={"entry": tool})
            continue
        lines.extend(_render_tool_entry(tool))

    output_path = (
        Path(__file__).resolve().parents[3] / "docs" / "modules" / "codeintel" / "tools.md"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    LOGGER.info("Generated CodeIntel MCP docs", extra={"output_path": str(output_path)})


if __name__ == "__main__":
    main()
