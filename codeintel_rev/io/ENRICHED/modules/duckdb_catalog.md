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
- from **collections.abc** import Callable, Iterator, Mapping, Sequence
- from **contextlib** import contextmanager
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **threading** import Lock
- from **time** import perf_counter
- from **typing** import TYPE_CHECKING, Any, ClassVar, Self, TypedDict, Unpack, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.io.duckdb_manager** import DuckDBManager, DuckDBQueryBuilder, DuckDBQueryOptions
- from **codeintel_rev.io.parquet_store** import extract_embeddings
- from **codeintel_rev.mcp_server.scope_utils** import LANGUAGE_EXTENSIONS, path_matches_glob
- from **codeintel_rev.typing** import NDArrayF32
- from **kgfoundry_common.logging** import get_logger
- from **(absolute)** import duckdb
- from **(absolute)** import numpy

## Definitions

- variable: `duckdb` (line 38)
- variable: `np` (line 39)
- variable: `LOGGER` (line 41)
- class: `IdMapMeta` (line 45)
- class: `_ScopeFilterLogInfo` (line 55)
- function: `_log_extra` (line 64)
- function: `_escape_identifier` (line 88)
- class: `_ScopeFilterSpec` (line 142)
- class: `StructureAnnotations` (line 159)
- class: `DuckDBCatalogOptions` (line 169)
- class: `_DuckDBQueryMixin` (line 178)
- class: `_LegacyOptions` (line 409)
- class: `DuckDBCatalog` (line 416)
- function: `_relation_exists` (line 1697)
- function: `relation_exists` (line 1731)
- function: `_file_checksum` (line 1749)
- function: `_parquet_hash` (line 1771)
- function: `ensure_faiss_idmap_view` (line 1799)
- function: `refresh_faiss_idmap_materialized` (line 1846)

## Graph Metrics

- **fan_in**: 11
- **fan_out**: 5
- **cycle_group**: 28

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 49
- recent churn 90: 49

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

DuckDBCatalog, IdMapMeta, StructureAnnotations, ensure_faiss_idmap_view, refresh_faiss_idmap_materialized, relation_exists

## Doc Health

- **summary**: DuckDB catalog for querying Parquet chunks.
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

- score: 3.22

## Side Effects

- database
- filesystem

## Complexity

- branches: 170
- cyclomatic: 171
- loc: 1945

## Doc Coverage

- `IdMapMeta` (class): summary=yes, examples=no — Metadata describing a materialized FAISS ID map join.
- `_ScopeFilterLogInfo` (class): summary=yes, examples=no — Container for scope filter logging inputs.
- `_log_extra` (function): summary=yes, params=mismatch, examples=no — Return structured log extras for catalog events.
- `_escape_identifier` (function): summary=yes, params=ok, examples=no — Return a DuckDB-escaped identifier string.
- `_ScopeFilterSpec` (class): summary=yes, examples=no — Structured scope filter metadata used during scoped queries.
- `StructureAnnotations` (class): summary=yes, examples=no — Structure-aware metadata joined onto explainability pools.
- `DuckDBCatalogOptions` (class): summary=yes, examples=no — Optional configuration bundle for DuckDB catalog instantiation.
- `_DuckDBQueryMixin` (class): summary=yes, examples=no — Chunk-level query helpers shared by :class:`DuckDBCatalog`.
- `_LegacyOptions` (class): summary=no, examples=no
- `DuckDBCatalog` (class): summary=yes, examples=no — DuckDB catalog for querying chunks.

## Tags

low-coverage, public-api
