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
- from **(absolute)** import logging
- from **collections.abc** import Callable, Iterator, Mapping, Sequence
- from **contextlib** import contextmanager
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **threading** import Lock
- from **typing** import TYPE_CHECKING, Any, ClassVar, Self, TypedDict, Unpack, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.io.duckdb_manager** import DuckDBManager, DuckDBQueryBuilder, DuckDBQueryOptions
- from **codeintel_rev.io.parquet_store** import extract_embeddings
- from **codeintel_rev.mcp_server.scope_utils** import LANGUAGE_EXTENSIONS, path_matches_glob
- from **codeintel_rev.typing** import NDArrayF32
- from **(absolute)** import duckdb
- from **(absolute)** import numpy

## Definitions

- variable: `duckdb` (line 35)
- variable: `np` (line 36)
- variable: `LOGGER` (line 38)
- class: `IdMapMeta` (line 42)
- function: `_escape_identifier` (line 51)
- class: `_ScopeFilterSpec` (line 105)
- class: `StructureAnnotations` (line 122)
- class: `_StructMaterializationPlan` (line 132)
- class: `DuckDBCatalogOptions` (line 210)
- class: `_DuckDBQueryMixin` (line 219)
- class: `_LegacyOptions` (line 433)
- class: `DuckDBCatalog` (line 440)
- function: `_relation_exists` (line 1630)
- function: `relation_exists` (line 1664)
- function: `_file_checksum` (line 1682)
- function: `_parquet_hash` (line 1704)
- function: `ensure_faiss_idmap_view` (line 1732)
- function: `refresh_faiss_idmap_materialized` (line 1776)

## Graph Metrics

- **fan_in**: 11
- **fan_out**: 5
- **cycle_group**: 28

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 50
- recent churn 90: 50

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

- score: 3.19

## Side Effects

- database
- filesystem

## Complexity

- branches: 151
- cyclomatic: 152
- loc: 1875

## Doc Coverage

- `IdMapMeta` (class): summary=yes, examples=no — Metadata describing a materialized FAISS ID map join.
- `_escape_identifier` (function): summary=yes, params=ok, examples=no — Return a DuckDB-escaped identifier string.
- `_ScopeFilterSpec` (class): summary=yes, examples=no — Structured scope filter metadata used during scoped queries.
- `StructureAnnotations` (class): summary=yes, examples=no — Structure-aware metadata joined onto explainability pools.
- `_StructMaterializationPlan` (class): summary=yes, examples=no — Precomputed SQL statements for struct table materialization.
- `DuckDBCatalogOptions` (class): summary=yes, examples=no — Optional configuration bundle for DuckDB catalog instantiation.
- `_DuckDBQueryMixin` (class): summary=yes, examples=no — Chunk-level query helpers shared by :class:`DuckDBCatalog`.
- `_LegacyOptions` (class): summary=no, examples=no
- `DuckDBCatalog` (class): summary=yes, examples=no — DuckDB catalog for querying chunks.
- `_relation_exists` (function): summary=yes, params=ok, examples=no — Return True when a table or view with ``name`` exists in the main schema.

## Tags

low-coverage, public-api
