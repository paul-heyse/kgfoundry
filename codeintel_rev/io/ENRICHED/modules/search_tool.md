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
- function: `handle_search` (line 29)
- function: `_merge_candidates` (line 101)
- function: `_build_url` (line 132)
- function: `_build_snippet` (line 151)
- function: `_normalize_search_input` (line 173)
- function: `_coerce_int` (line 203)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 2
- **cycle_group**: 143

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 2
- recent churn 90: 2

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Lightweight search helpers used by the in-process MCP harness.
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

- score: 2.18

## Side Effects

- none detected

## Raises

NotImplementedError

## Complexity

- branches: 35
- cyclomatic: 36
- loc: 240

## Doc Coverage

- `CatalogProtocol` (class): summary=yes, examples=no — Protocol describing the catalog surface used by the lightweight MCP tools.
- `SearchDeps` (class): summary=yes, examples=no — Dependencies required to execute the light search helper.
- `handle_search` (function): summary=yes, params=ok, examples=no — Execute a lightweight search suitable for MCP tests or tooling.
- `_merge_candidates` (function): summary=no, examples=no
- `_build_url` (function): summary=yes, params=ok, examples=no — Build a repo:// URL from chunk metadata row.
- `_build_snippet` (function): summary=yes, params=ok, examples=no — Build a text snippet from chunk metadata row.
- `_normalize_search_input` (function): summary=yes, params=ok, examples=no — Normalize and validate search tool input arguments.
- `_coerce_int` (function): summary=yes, params=ok, examples=no — Coerce a value to an integer with fallback to default.

## Tags

low-coverage
