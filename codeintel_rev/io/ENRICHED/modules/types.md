# mcp_server/types.py

## Docstring

```
Typed DTOs and JSON Schema helpers for MCP search/fetch tools.
```

## Imports

- from **__future__** import annotations
- from **typing** import Any, Literal
- from **(absolute)** import msgspec

## Definitions

- class: `SearchInput` (line 12)
- class: `SearchResultItem` (line 20)
- class: `SearchOutput` (line 32)
- class: `FetchInput` (line 41)
- class: `FetchedObject` (line 49)
- class: `FetchOutput` (line 59)
- function: `search_input_schema` (line 65)
- function: `search_output_schema` (line 85)
- function: `fetch_input_schema` (line 121)
- function: `fetch_output_schema` (line 144)

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 1
- **cycle_group**: 124

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 1
- recent churn 90: 1

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Typed DTOs and JSON Schema helpers for MCP search/fetch tools.
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

- score: 1.40

## Side Effects

- none detected

## Complexity

- branches: 0
- cyclomatic: 1
- loc: 173

## Doc Coverage

- `SearchInput` (class): summary=yes, examples=no — Incoming payload for the lightweight MCP search tool.
- `SearchResultItem` (class): summary=yes, examples=no — Single search result entry returned by the lightweight MCP tools.
- `SearchOutput` (class): summary=yes, examples=no — Structured search response returned to the caller.
- `FetchInput` (class): summary=yes, examples=no — Incoming payload for the lightweight MCP fetch tool.
- `FetchedObject` (class): summary=yes, examples=no — Hydrated chunk entry returned from fetch operations.
- `FetchOutput` (class): summary=yes, examples=no — Fetch response wrapping one or more hydrated chunk objects.
- `search_input_schema` (function): summary=yes, params=ok, examples=no — Return the JSON Schema describing search tool inputs.
- `search_output_schema` (function): summary=yes, params=ok, examples=no — Return the JSON Schema describing search tool outputs.
- `fetch_input_schema` (function): summary=yes, params=ok, examples=no — Return the JSON Schema describing fetch tool inputs.
- `fetch_output_schema` (function): summary=yes, params=ok, examples=no — Return the JSON Schema describing fetch tool outputs.

## Tags

low-coverage
