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

- function: `_parse_pragmas` (line 61)
- variable: `DuckDBConnection` (line 81)
- variable: `DuckDBConnection` (line 83)
- class: `_DuckDBModule` (line 86)
- class: `DuckConn` (line 112)
- class: `DuckDBIngestContext` (line 119)
- function: `_duckdb` (line 138)
- function: `ensure_schema` (line 150)
- function: `ingest_modules_jsonl` (line 195)
- function: `_load_json_rows` (line 235)
- function: `_coerce_value` (line 253)
- function: `_apply_pragmas` (line 262)
- function: `_ingest_via_native_json` (line 269)
- function: `_ingest_via_python` (line 300)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 82

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 6
- recent churn 90: 6

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

DuckConn, DuckDBIngestContext, ensure_schema, ingest_modules_jsonl

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

- score: 2.04

## Side Effects

- database
- filesystem

## Complexity

- branches: 31
- cyclomatic: 32
- loc: 318

## Doc Coverage

- `_parse_pragmas` (function): summary=no, examples=no
- `_DuckDBModule` (class): summary=yes, examples=no — Protocol describing the subset of duckdb module APIs we rely on.
- `DuckConn` (class): summary=yes, examples=no — Connection metadata for enrichment DuckDB ingestion.
- `DuckDBIngestContext` (class): summary=yes, examples=no — Dependency providers and options for DuckDB ingestion routines.
- `_duckdb` (function): summary=yes, params=ok, examples=no — Import duckdb on demand to keep it optional at runtime.
- `ensure_schema` (function): summary=yes, params=mismatch, examples=no — Create the ``modules`` table if it does not already exist.
- `ingest_modules_jsonl` (function): summary=yes, params=ok, examples=no — Load modules.jsonl rows into DuckDB, replacing existing paths.
- `_load_json_rows` (function): summary=no, examples=no
- `_coerce_value` (function): summary=no, examples=no
- `_apply_pragmas` (function): summary=no, examples=no

## Tags

low-coverage, public-api
