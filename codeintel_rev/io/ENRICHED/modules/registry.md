# mcp_server/registry.py

## Docstring

```
In-process registry for the lightweight MCP testing harness.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Callable
- from **dataclasses** import dataclass
- from **typing** import Any
- from **(absolute)** import msgspec
- from **codeintel_rev.mcp_server.fetch_tool** import handle_fetch
- from **codeintel_rev.mcp_server.search_tool** import SearchDeps, handle_search
- from **codeintel_rev.mcp_server.types** import FetchOutput, fetch_input_schema, fetch_output_schema, search_input_schema, search_output_schema

## Definitions

- class: `McpDeps` (line 23)
- function: `list_tools` (line 31)
- function: `call_tool` (line 55)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 4
- **cycle_group**: 126

## Ownership

- bus factor: 0.00
- recent churn 30: 0
- recent churn 90: 0

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: In-process registry for the lightweight MCP testing harness.
- has summary: yes
- param parity: no
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

- score: 1.80

## Side Effects

- none detected

## Complexity

- branches: 4
- cyclomatic: 5
- loc: 82

## Doc Coverage

- `McpDeps` (class): summary=yes, examples=no — Dependencies required for running the lightweight MCP tools.
- `list_tools` (function): summary=yes, params=ok, examples=no — Return tool metadata compatible with MCP /tools/list responses.
- `call_tool` (function): summary=yes, params=mismatch, examples=no — Execute a tool using the provided dependencies.

## Tags

low-coverage
