# mcp_server/search_tool.py

## Docstring

```
Lightweight search helpers used by the in-process MCP harness.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Callable, Mapping, Sequence
- from **dataclasses** import dataclass
- from **typing** import Protocol
- from **codeintel_rev.mcp_server.types** import SearchInput, SearchOutput, SearchResultItem

## Definitions

- class: `CatalogProtocol` (line 12)
- class: `SearchDeps` (line 21)
- function: `handle_search` (line 28)
- function: `_merge_candidates` (line 83)
- function: `_build_url` (line 114)
- function: `_build_snippet` (line 121)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 2
- **cycle_group**: 124

## Ownership

- bus factor: 0.00
- recent churn 30: 0
- recent churn 90: 0

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Lightweight search helpers used by the in-process MCP harness.
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

- score: 2.10

## Side Effects

- none detected

## Raises

NotImplementedError

## Complexity

- branches: 26
- cyclomatic: 27
- loc: 129

## Doc Coverage

- `CatalogProtocol` (class): summary=yes, examples=no — Protocol describing the catalog surface used by the lightweight MCP tools.
- `SearchDeps` (class): summary=yes, examples=no — Dependencies required to execute the light search helper.
- `handle_search` (function): summary=yes, params=mismatch, examples=no — Execute a lightweight search suitable for MCP tests or tooling.
- `_merge_candidates` (function): summary=no, examples=no
- `_build_url` (function): summary=no, examples=no
- `_build_snippet` (function): summary=no, examples=no

## Tags

low-coverage
