# enrich/scip_reader.py

## Docstring

```
Lightweight helpers for loading and querying SCIP JSON indices.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **dataclasses** import dataclass, field
- from **pathlib** import Path
- from **typing** import Any
- from **(absolute)** import orjson

## Definitions

- function: `_loads` (line 17)
- class: `Occurrence` (line 37)
- class: `SymbolInfo` (line 46)
- class: `Document` (line 56)
- class: `SCIPIndex` (line 65)
- function: `_parse_document` (line 142)

## Graph Metrics

- **fan_in**: 4
- **fan_out**: 1
- **cycle_group**: 12

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

- **summary**: Lightweight helpers for loading and querying SCIP JSON indices.
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

## Config References

- enrich/tagging_rules.yaml
- enrich/PLAYBOOK.md
- enrich/README.md

## Hotspot

- score: 2.03

## Side Effects

- filesystem

## Complexity

- branches: 11
- cyclomatic: 12
- loc: 182

## Doc Coverage

- `_loads` (function): summary=yes, params=ok, examples=no — Deserialize JSON bytes using orjson when available.
- `Occurrence` (class): summary=yes, examples=no — Symbol occurrence entry extracted from the SCIP schema.
- `SymbolInfo` (class): summary=yes, examples=no — Symbol metadata bundled with a document.
- `Document` (class): summary=yes, examples=no — SCIP document entry (per source file).
- `SCIPIndex` (class): summary=yes, examples=no — In-memory representation of a SCIP dataset.
- `_parse_document` (function): summary=yes, params=ok, examples=no — Convert a raw SCIP document record into a :class:`Document`.

## Tags

low-coverage
