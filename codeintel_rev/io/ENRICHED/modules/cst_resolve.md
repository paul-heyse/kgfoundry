# cst_build/cst_resolve.py

## Docstring

```
Stitch CST nodes to module summary rows and SCIP symbols.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **collections.abc** import Iterable, Mapping
- from **dataclasses** import dataclass, replace
- from **pathlib** import Path
- from **typing** import Any, ClassVar
- from **codeintel_rev.cst_build.cst_schema** import NodeRecord, StitchCandidate, StitchInfo
- from **codeintel_rev.enrich.scip_reader** import Document, SCIPIndex

## Definitions

- class: `ModuleRow` (line 17)
- class: `StitchCounters` (line 25)
- class: `_SymbolCandidate` (line 59)
- class: `SCIPResolver` (line 66)
- function: `load_modules` (line 172)
- function: `load_scip_index` (line 208)
- function: `stitch_nodes` (line 227)
- function: `_normalize_path` (line 288)
- function: `_collect_candidates` (line 297)
- function: `_select_best_candidate` (line 310)
- function: `_symbol_name_hint` (line 337)
- function: `_symbol_qname_hint` (line 350)
- function: `_normalize_qname` (line 363)
- function: `_score_candidate` (line 369)

## Graph Metrics

- **fan_in**: 2
- **fan_out**: 3
- **cycle_group**: 110

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

- **summary**: Stitch CST nodes to module summary rows and SCIP symbols.
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

- score: 2.50

## Side Effects

- filesystem

## Complexity

- branches: 59
- cyclomatic: 60
- loc: 392

## Doc Coverage

- `ModuleRow` (class): summary=yes, examples=no — Lightweight projection of a module.jsonl row.
- `StitchCounters` (class): summary=yes, examples=no — Aggregate match counters used for index.json.
- `_SymbolCandidate` (class): summary=no, examples=no
- `SCIPResolver` (class): summary=yes, examples=no — Best-effort matcher between CST spans and SCIP occurrences.
- `load_modules` (function): summary=yes, params=ok, examples=no — Load modules.jsonl rows into a lookup keyed by normalized path.
- `load_scip_index` (function): summary=yes, params=ok, examples=no — Load the SCIP resolver when ``path`` exists.
- `stitch_nodes` (function): summary=yes, params=ok, examples=no — Attach StitchInfo to ``nodes``.
- `_normalize_path` (function): summary=no, examples=no
- `_collect_candidates` (function): summary=no, examples=no
- `_select_best_candidate` (function): summary=no, examples=no

## Tags

low-coverage
