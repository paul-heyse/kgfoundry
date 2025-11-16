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

## Definitions

- variable: `mcp` (line 23)
- variable: `app_context` (line 28)
- function: `get_context` (line 33)
- function: `set_scope` (line 61)
- function: `list_paths` (line 83)
- function: `open_file` (line 130)
- function: `search_text` (line 167)
- function: `blame_range` (line 218)
- function: `file_history` (line 252)
- function: `report_latest_run` (line 279)
- function: `file_resource` (line 295)
- function: `prompt_code_review` (line 319)
- function: `build_http_app` (line 335)

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 5
- **cycle_group**: 36

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 16
- recent churn 90: 16

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

app_context, build_http_app, get_context, mcp

## Doc Health

- **summary**: FastMCP server with QueryScope tools.
- has summary: yes
- param parity: yes
- examples present: no

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Hotspot

- score: 1.96

## Side Effects

- none detected

## Complexity

- branches: 4
- cyclomatic: 5
- loc: 374

## Doc Coverage

- `get_context` (function): summary=yes, params=ok, examples=no — Extract ApplicationContext from context variable.
- `set_scope` (function): summary=yes, params=ok, examples=no — Set query scope for subsequent operations.
- `list_paths` (function): summary=yes, params=ok, examples=no — List files in scope (async).
- `open_file` (function): summary=yes, params=ok, examples=no — Read file content.
- `search_text` (function): summary=yes, params=ok, examples=no — Fast text search (ripgrep-like).
- `blame_range` (function): summary=yes, params=ok, examples=no — Git blame for line range (async).
- `file_history` (function): summary=yes, params=ok, examples=no — Get file commit history (async).
- `report_latest_run` (function): summary=yes, params=ok, examples=no — Return metadata about recent run reports (disabled in the simplified runtime).
- `file_resource` (function): summary=yes, params=ok, examples=no — Serve file content as resource.
- `prompt_code_review` (function): summary=yes, params=ok, examples=no — Code review prompt template.

## Tags

low-coverage, public-api
