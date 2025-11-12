# io/duckdb_catalog.py

## Docstring

```
DuckDB catalog for querying Parquet chunks.

Provides SQL views over Parquet directories and query helpers for fast
chunk retrieval and joins.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import hashlib
- from **collections.abc** import Iterator, Sequence
- from **contextlib** import contextmanager, suppress
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **threading** import Lock
- from **time** import perf_counter
- from **typing** import TYPE_CHECKING, Any, Self, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.io.duckdb_manager** import DuckDBManager, DuckDBQueryBuilder, DuckDBQueryOptions
- from **codeintel_rev.io.parquet_store** import extract_embeddings
- from **codeintel_rev.mcp_server.scope_utils** import LANGUAGE_EXTENSIONS, path_matches_glob
- from **codeintel_rev.observability.timeline** import current_timeline
- from **codeintel_rev.typing** import NDArrayF32
- from **kgfoundry_common.logging** import get_logger
- from **kgfoundry_common.prometheus** import build_histogram
- from **(absolute)** import duckdb
- from **(absolute)** import numpy

## Definitions

- variable: `duckdb` (line 38)
- variable: `np` (line 39)
- variable: `LOGGER` (line 41)
- function: `_log_extra` (line 44)
- class: `_ScopeFilterSpec` (line 83)
- class: `DuckDBCatalog` (line 99)

## Graph Metrics

- **fan_in**: 6
- **fan_out**: 6
- **cycle_group**: 65

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 31
- recent churn 90: 31

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

DuckDBCatalog

## Doc Health

- **summary**: DuckDB catalog for querying Parquet chunks.
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

- score: 2.94

## Side Effects

- database
- filesystem

## Complexity

- branches: 93
- cyclomatic: 94
- loc: 1216

## Doc Coverage

- `_log_extra` (function): summary=yes, params=mismatch, examples=no — Return structured log extras for catalog events.
- `_ScopeFilterSpec` (class): summary=yes, examples=no — Structured scope filter metadata used during scoped queries.
- `DuckDBCatalog` (class): summary=yes, examples=no — DuckDB catalog for querying chunks.

## Tags

low-coverage, public-api
