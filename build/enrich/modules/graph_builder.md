# graph_builder.py

## Docstring

```
Import graph builder utilities.
```

## Imports

- from **__future__** import annotations
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import Any
- from **(absolute)** import polars
- from **codeintel_rev.module_utils** import import_targets_for_entry, module_name_candidates, normalize_module_name

## Definitions

- variable: `pl` (line 13)
- class: `ImportGraph` (line 23)
- function: `build_import_graph` (line 32)
- function: `write_import_graph` (line 87)
- function: `_tarjan_scc` (line 107)

## Dependency Graph

- **fan_in**: 1
- **fan_out**: 2
- **cycle_group**: 5

## Doc Metrics

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

## Hotspot Score

- score: 2.09

## Side Effects

- filesystem

## Complexity

- branches: 25
- cyclomatic: 26
- loc: 142

## Doc Coverage

- `ImportGraph` (class): summary=yes, examples=no — Graph representation of intra-repo imports.
- `build_import_graph` (function): summary=yes, params=ok, examples=no — Build an import graph across repo modules.
- `write_import_graph` (function): summary=yes, params=mismatch, examples=no — Write import edges to Parquet (or JSONL fallback).
- `_tarjan_scc` (function): summary=no, examples=no

## Tags

low-coverage
