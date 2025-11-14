# mcp_server/server_symbols.py

## Docstring

```
Symbol MCP tool registrations (pure move from server.py).
```

## Imports

- from **__future__** import annotations
- from **codeintel_rev.mcp_server.error_handling** import handle_adapter_errors
- from **codeintel_rev.mcp_server.schemas** import Location, SymbolInfo
- from **codeintel_rev.mcp_server.server** import get_context, mcp
- from **codeintel_rev.mcp_server.telemetry** import tool_operation_scope

## Definitions

- function: `symbol_search` (line 16)
- function: `definition_at` (line 108)
- function: `references_at` (line 189)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 4
- **cycle_group**: 147

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 3
- recent churn 90: 3

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Symbol MCP tool registrations (pure move from server.py).
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

- score: 2.06

## Side Effects

- none detected

## Complexity

- branches: 16
- cyclomatic: 17
- loc: 263

## Doc Coverage

- `symbol_search` (function): summary=yes, params=ok, examples=no — Search for symbols (functions, classes, etc).
- `definition_at` (function): summary=yes, params=ok, examples=no — Find definition at position.
- `references_at` (function): summary=yes, params=ok, examples=no — Find references at position.

## Tags

low-coverage
