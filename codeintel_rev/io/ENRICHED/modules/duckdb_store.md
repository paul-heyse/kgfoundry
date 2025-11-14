# enrich/duckdb_store.py

## Docstring

```
Utilities for loading enrichment artifacts into DuckDB.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **codeintel_rev.typing** import gate_import

## Definitions

- class: `DuckConn` (line 54)
- function: `_duckdb` (line 60)
- function: `ensure_schema` (line 71)
- function: `ingest_modules_jsonl` (line 115)
- function: `_load_json_rows` (line 158)
- function: `_coerce_value` (line 176)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 94

## Ownership

- bus factor: 0.00
- recent churn 30: 0
- recent churn 90: 0

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

DuckConn, ensure_schema, ingest_modules_jsonl

## Doc Health

- **summary**: Utilities for loading enrichment artifacts into DuckDB.
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

## Config References

- enrich/tagging_rules.yaml
- enrich/PLAYBOOK.md
- enrich/README.md

## Hotspot

- score: 1.82

## Side Effects

- filesystem

## Complexity

- branches: 14
- cyclomatic: 15
- loc: 183

## Doc Coverage

- `DuckConn` (class): summary=yes, examples=no — Connection metadata for enrichment DuckDB ingestion.
- `_duckdb` (function): summary=yes, params=ok, examples=no — Import duckdb on demand to keep it optional at runtime.
- `ensure_schema` (function): summary=yes, params=mismatch, examples=no — Create the ``modules`` table if it does not already exist.
- `ingest_modules_jsonl` (function): summary=yes, params=ok, examples=no — Load modules.jsonl rows into DuckDB, replacing existing paths.
- `_load_json_rows` (function): summary=no, examples=no
- `_coerce_value` (function): summary=no, examples=no

## Tags

low-coverage, public-api
