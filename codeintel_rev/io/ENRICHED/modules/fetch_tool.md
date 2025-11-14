# mcp_server/fetch_tool.py

## Docstring

```
Lightweight fetch helper used by the in-process MCP harness.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Mapping, Sequence
- from **typing** import Literal
- from **codeintel_rev.mcp_server.types** import FetchedObject, FetchInput, FetchOutput

## Definitions

- class: `CatalogProtocol` (line 11)
- function: `handle_fetch` (line 19)
- function: `_build_url` (line 78)
- function: `_normalize_fetch_input` (line 97)
- function: `_coerce_optional_int` (line 127)
- function: `_coerce_object_ids` (line 145)
- function: `_coerce_resolve` (line 179)
- function: `_coerce_int` (line 212)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 2
- **cycle_group**: 126

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

- **summary**: Lightweight fetch helper used by the in-process MCP harness.
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

- score: 2.11

## Side Effects

- none detected

## Raises

NotImplementedError

## Complexity

- branches: 27
- cyclomatic: 28
- loc: 249

## Doc Coverage

- `CatalogProtocol` (class): summary=yes, examples=no — Protocol describing the catalog lookups required for fetch.
- `handle_fetch` (function): summary=yes, params=ok, examples=no — Hydrate chunk IDs using the provided catalog.
- `_build_url` (function): summary=yes, params=ok, examples=no — Build a repo:// URL from chunk metadata row.
- `_normalize_fetch_input` (function): summary=yes, params=ok, examples=no — Normalize and validate fetch tool input arguments.
- `_coerce_optional_int` (function): summary=yes, params=ok, examples=no — Coerce an optional value to int or None.
- `_coerce_object_ids` (function): summary=yes, params=ok, examples=no — Coerce object IDs to a list of non-empty strings.
- `_coerce_resolve` (function): summary=yes, params=ok, examples=no — Coerce resolve option to a valid literal value.
- `_coerce_int` (function): summary=yes, params=ok, examples=no — Coerce a value to an integer with fallback to default.

## Tags

low-coverage
