# uses_builder.py

## Docstring

```
SCIP-based symbol use graph helpers.
```

## Imports

- from **__future__** import annotations
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import cast
- from **codeintel_rev.enrich.scip_reader** import SCIPIndex
- from **codeintel_rev.polars_support** import resolve_polars_frame_factory
- from **codeintel_rev.typing** import PolarsModule, gate_import

## Definitions

- class: `UseGraph` (line 16)
- function: `build_use_graph` (line 24)
- function: `write_use_graph` (line 60)
- function: `_is_definition` (line 86)
- function: `_write_parquet` (line 106)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 3
- **cycle_group**: 10

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 4
- recent churn 90: 4

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: SCIP-based symbol use graph helpers.
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

- filesystem

## Complexity

- branches: 16
- cyclomatic: 17
- loc: 131

## Doc Coverage

- `UseGraph` (class): summary=yes, examples=no — Definition-to-use relationships summarised by file.
- `build_use_graph` (function): summary=yes, params=ok, examples=no — Build a use graph from SCIP occurrences.
- `write_use_graph` (function): summary=yes, params=ok, examples=no — Persist use graph edges to Parquet (or JSONL fallback).
- `_is_definition` (function): summary=yes, params=ok, examples=no — Check if any role indicates a definition.
- `_write_parquet` (function): summary=yes, params=ok, examples=no — Write records via polars when available.

## Tags

low-coverage
