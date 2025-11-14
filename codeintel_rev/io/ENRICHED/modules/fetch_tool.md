# mcp_server/fetch_tool.py

## Docstring

```
Lightweight fetch helper used by the in-process MCP harness.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Sequence
- from **codeintel_rev.mcp_server.types** import FetchedObject, FetchInput, FetchOutput

## Definitions

- class: `CatalogProtocol` (line 10)
- function: `handle_fetch` (line 18)
- function: `_build_url` (line 54)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 125

## Ownership

- bus factor: 0.00
- recent churn 30: 0
- recent churn 90: 0

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Lightweight fetch helper used by the in-process MCP harness.
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

- score: 1.68

## Side Effects

- none detected

## Raises

NotImplementedError

## Complexity

- branches: 8
- cyclomatic: 9
- loc: 59

## Doc Coverage

- `CatalogProtocol` (class): summary=yes, examples=no — Protocol describing the catalog lookups required for fetch.
- `handle_fetch` (function): summary=yes, params=mismatch, examples=no — Hydrate chunk IDs using the provided catalog.
- `_build_url` (function): summary=no, examples=no

## Tags

low-coverage
