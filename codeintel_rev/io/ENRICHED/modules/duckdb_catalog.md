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
- from **collections.abc** import Iterator, Mapping, Sequence
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
- from **codeintel_rev.telemetry.decorators** import span_context
- from **codeintel_rev.typing** import NDArrayF32
- from **kgfoundry_common.logging** import get_logger
- from **kgfoundry_common.prometheus** import build_histogram
- from **(absolute)** import duckdb
- from **(absolute)** import numpy

## Definitions

- variable: `duckdb` (line 39)
- variable: `np` (line 40)
- variable: `LOGGER` (line 42)
- function: `_log_extra` (line 45)
- class: `_ScopeFilterSpec` (line 114)
- class: `StructureAnnotations` (line 131)
- class: `DuckDBCatalogOptions` (line 141)
- class: `_DuckDBQueryMixin` (line 150)
- class: `DuckDBCatalog` (line 401)

## Graph Metrics

- **fan_in**: 8
- **fan_out**: 7
- **cycle_group**: 67

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 35
- recent churn 90: 35

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

DuckDBCatalog, StructureAnnotations

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

- score: 3.13

## Side Effects

- database
- filesystem

## Complexity

- branches: 135
- cyclomatic: 136
- loc: 1593

## Doc Coverage

- `_log_extra` (function): summary=yes, params=mismatch, examples=no — Return structured log extras for catalog events.
- `_ScopeFilterSpec` (class): summary=yes, examples=no — Structured scope filter metadata used during scoped queries.
- `StructureAnnotations` (class): summary=yes, examples=no — Structure-aware metadata joined onto explainability pools.
- `DuckDBCatalogOptions` (class): summary=yes, examples=no — Optional configuration bundle for DuckDB catalog instantiation.
- `_DuckDBQueryMixin` (class): summary=yes, examples=no — Chunk-level query helpers shared by :class:`DuckDBCatalog`.
- `DuckDBCatalog` (class): summary=yes, examples=no — DuckDB catalog for querying chunks.

## Tags

low-coverage, public-api
