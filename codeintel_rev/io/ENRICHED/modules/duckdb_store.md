# enrich/duckdb_store.py

## Docstring

```
Utilities for loading enrichment artifacts into DuckDB.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **(absolute)** import os
- from **(absolute)** import re
- from **collections.abc** import Sequence
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING, Any, Protocol, cast
- from **codeintel_rev.typing** import gate_import
- from **(absolute)** import duckdb

## Definitions

- variable: `DuckDBConnection` (line 63)
- variable: `DuckDBConnection` (line 65)
- class: `_DuckDBModule` (line 68)
- class: `DuckConn` (line 94)
- function: `_duckdb` (line 100)
- function: `ensure_schema` (line 112)
- function: `ingest_modules_jsonl` (line 156)
- function: `_load_json_rows` (line 186)
- function: `_coerce_value` (line 204)
- function: `_apply_pragmas` (line 213)
- function: `_ingest_via_native_json` (line 226)
- function: `_ingest_via_python` (line 257)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 78

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 5
- recent churn 90: 5

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

- score: 2.00

## Side Effects

- database
- filesystem

## Complexity

- branches: 27
- cyclomatic: 28
- loc: 275

## Doc Coverage

- `_DuckDBModule` (class): summary=yes, examples=no — Protocol describing the subset of duckdb module APIs we rely on.
- `DuckConn` (class): summary=yes, examples=no — Connection metadata for enrichment DuckDB ingestion.
- `_duckdb` (function): summary=yes, params=ok, examples=no — Import duckdb on demand to keep it optional at runtime.
- `ensure_schema` (function): summary=yes, params=mismatch, examples=no — Create the ``modules`` table if it does not already exist.
- `ingest_modules_jsonl` (function): summary=yes, params=ok, examples=no — Load modules.jsonl rows into DuckDB, replacing existing paths.
- `_load_json_rows` (function): summary=no, examples=no
- `_coerce_value` (function): summary=no, examples=no
- `_apply_pragmas` (function): summary=no, examples=no
- `_ingest_via_native_json` (function): summary=no, examples=no
- `_ingest_via_python` (function): summary=no, examples=no

## Tags

low-coverage, public-api
