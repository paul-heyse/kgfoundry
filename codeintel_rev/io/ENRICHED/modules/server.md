# mcp_server/server.py

## Docstring

```
FastMCP server with QueryScope tools.

Implements full MCP tool catalog for code intelligence.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import contextvars
- from **(absolute)** import importlib
- from **fastmcp** import FastMCP
- from **starlette.types** import ASGIApp
- from **codeintel_rev.app.capabilities** import Capabilities
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.mcp_server.adapters** import files
- from **codeintel_rev.mcp_server.adapters** import history
- from **codeintel_rev.mcp_server.adapters** import text_search
- from **codeintel_rev.mcp_server.error_handling** import handle_adapter_errors
- from **codeintel_rev.mcp_server.schemas** import ScopeIn
- from **codeintel_rev.mcp_server.telemetry** import tool_operation_scope

## Definitions

- variable: `mcp` (line 24)
- variable: `app_context` (line 29)
- function: `get_context` (line 34)
- function: `set_scope` (line 62)
- function: `list_paths` (line 85)
- function: `open_file` (line 138)
- function: `search_text` (line 179)
- function: `blame_range` (line 237)
- function: `file_history` (line 277)
- function: `file_resource` (line 312)
- function: `prompt_code_review` (line 336)
- function: `build_http_app` (line 352)

## Dependency Graph

- **fan_in**: 3
- **fan_out**: 6
- **cycle_group**: 49

## Declared Exports (__all__)

app_context, build_http_app, get_context, mcp

## Tags

public-api
