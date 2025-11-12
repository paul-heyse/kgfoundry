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
- class: `_ScopeFilterSpec` (line 78)
- class: `DuckDBCatalog` (line 94)

## Dependency Graph

- **fan_in**: 6
- **fan_out**: 6
- **cycle_group**: 61

## Declared Exports (__all__)

DuckDBCatalog

## Doc Metrics

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

## Hotspot Score

- score: 2.91

## Side Effects

- database
- filesystem

## Complexity

- branches: 85
- cyclomatic: 86
- loc: 1073

## Doc Coverage

- `_log_extra` (function): summary=yes, params=mismatch, examples=no — Return structured log extras for catalog events.
- `_ScopeFilterSpec` (class): summary=yes, examples=no — Structured scope filter metadata used during scoped queries.
- `DuckDBCatalog` (class): summary=yes, examples=no — DuckDB catalog for querying chunks.

## Tags

low-coverage, public-api
