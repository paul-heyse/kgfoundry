# graph_builder.py

## Docstring

```
Import graph builder utilities.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Mapping, Sequence
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import Any, cast
- from **codeintel_rev.module_utils** import import_targets_for_entry, module_name_candidates, normalize_module_name
- from **codeintel_rev.polars_support** import resolve_polars_frame_factory
- from **codeintel_rev.typing** import PolarsModule, gate_import

## Definitions

- class: `ImportGraph` (line 21)
- function: `build_import_graph` (line 30)
- function: `write_import_graph` (line 85)
- function: `_tarjan_scc` (line 102)
- function: `_write_parquet` (line 164)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 3
- **cycle_group**: 99

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 7
- recent churn 90: 7

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Import graph builder utilities.
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

- score: 2.19

## Side Effects

- filesystem

## Complexity

- branches: 26
- cyclomatic: 27
- loc: 189

## Doc Coverage

- `ImportGraph` (class): summary=yes, examples=no — Graph representation of intra-repo imports.
- `build_import_graph` (function): summary=yes, params=ok, examples=no — Build an import graph across repo modules.
- `write_import_graph` (function): summary=yes, params=mismatch, examples=no — Write import edges to Parquet (or JSONL fallback).
- `_tarjan_scc` (function): summary=no, examples=no
- `_write_parquet` (function): summary=yes, params=ok, examples=no — Persist records to Parquet via polars when available.

## Tags

low-coverage
