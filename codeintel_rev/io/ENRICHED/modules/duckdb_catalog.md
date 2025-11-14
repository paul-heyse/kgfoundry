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
- from **contextlib** import contextmanager, suppress
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **threading** import Lock
- from **time** import perf_counter
- from **typing** import TYPE_CHECKING, Any, ClassVar, Self, TypedDict, Unpack, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.io.duckdb_manager** import DuckDBManager, DuckDBQueryBuilder, DuckDBQueryOptions
- from **codeintel_rev.io.parquet_store** import extract_embeddings
- from **codeintel_rev.mcp_server.scope_utils** import LANGUAGE_EXTENSIONS, path_matches_glob
- from **codeintel_rev.observability.otel** import record_span_event
- from **codeintel_rev.observability.timeline** import current_timeline
- from **codeintel_rev.telemetry.decorators** import span_context
- from **codeintel_rev.telemetry.steps** import StepEvent, emit_step
- from **codeintel_rev.typing** import NDArrayF32
- from **kgfoundry_common.logging** import get_logger
- from **kgfoundry_common.prometheus** import build_histogram
- from **(absolute)** import duckdb
- from **(absolute)** import numpy

## Definitions

- variable: `duckdb` (line 43)
- variable: `np` (line 44)
- variable: `LOGGER` (line 46)
- class: `IdMapMeta` (line 50)
- function: `_log_extra` (line 59)
- class: `_ScopeFilterSpec` (line 133)
- class: `StructureAnnotations` (line 150)
- class: `DuckDBCatalogOptions` (line 160)
- class: `_DuckDBQueryMixin` (line 169)
- class: `_LegacyOptions` (line 435)
- class: `DuckDBCatalog` (line 442)
- function: `_relation_exists` (line 1632)
- function: `relation_exists` (line 1666)
- function: `_file_checksum` (line 1684)
- function: `_parquet_hash` (line 1706)
- function: `ensure_faiss_idmap_view` (line 1724)
- function: `refresh_faiss_idmap_materialized` (line 1755)

## Graph Metrics

- **fan_in**: 9
- **fan_out**: 9
- **cycle_group**: 76

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 40
- recent churn 90: 40

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

- score: 3.23

## Side Effects

- database
- filesystem

## Complexity

- branches: 147
- cyclomatic: 148
- loc: 1836

## Doc Coverage

- `IdMapMeta` (class): summary=yes, examples=no — Metadata describing a materialized FAISS ID map join.
- `_log_extra` (function): summary=yes, params=mismatch, examples=no — Return structured log extras for catalog events.
- `_ScopeFilterSpec` (class): summary=yes, examples=no — Structured scope filter metadata used during scoped queries.
- `StructureAnnotations` (class): summary=yes, examples=no — Structure-aware metadata joined onto explainability pools.
- `DuckDBCatalogOptions` (class): summary=yes, examples=no — Optional configuration bundle for DuckDB catalog instantiation.
- `_DuckDBQueryMixin` (class): summary=yes, examples=no — Chunk-level query helpers shared by :class:`DuckDBCatalog`.
- `_LegacyOptions` (class): summary=no, examples=no
- `DuckDBCatalog` (class): summary=yes, examples=no — DuckDB catalog for querying chunks.
- `_relation_exists` (function): summary=yes, params=ok, examples=no — Return True when a table or view with ``name`` exists in the main schema.
- `relation_exists` (function): summary=yes, params=ok, examples=no — Public helper returning True when a DuckDB relation exists.

## Tags

low-coverage, public-api
