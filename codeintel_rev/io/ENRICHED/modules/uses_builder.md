# uses_builder.py

## Docstring

```
SCIP-based symbol use graph helpers.
```

## Imports

- from **__future__** import annotations
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **(absolute)** import polars
- from **codeintel_rev.enrich.scip_reader** import SCIPIndex

## Definitions

- variable: `pl` (line 12)
- class: `UseGraph` (line 18)
- function: `build_use_graph` (line 26)
- function: `write_use_graph` (line 57)
- function: `_is_definition` (line 84)

## Dependency Graph

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 11

## Doc Metrics

- **summary**: SCIP-based symbol use graph helpers.
- has summary: yes
- param parity: no
- examples present: no

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Side Effects

- filesystem

## Complexity

- branches: 15
- cyclomatic: 16
- loc: 90

## Doc Coverage

- `UseGraph` (class): summary=yes, examples=no — Definition-to-use relationships summarised by file.
- `build_use_graph` (function): summary=yes, params=mismatch, examples=no — Build a use graph from SCIP occurrences.
- `write_use_graph` (function): summary=yes, params=ok, examples=no — Persist use graph edges to Parquet (or JSONL fallback).
- `_is_definition` (function): summary=no, examples=no
