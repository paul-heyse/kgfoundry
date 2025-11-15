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
- from **codeintel_rev.observability.execution_ledger** import step
- from **codeintel_rev.observability.otel** import record_span_event
- from **codeintel_rev.observability.semantic_conventions** import Attrs
- from **codeintel_rev.observability.timeline** import Timeline, current_timeline
- from **codeintel_rev.telemetry.decorators** import span_context
- from **codeintel_rev.telemetry.otel_metrics** import build_histogram
- from **codeintel_rev.telemetry.steps** import StepEvent, emit_step
- from **codeintel_rev.typing** import NDArrayF32
- from **kgfoundry_common.logging** import get_logger
- from **(absolute)** import duckdb
- from **(absolute)** import numpy

## Definitions

- variable: `duckdb` (line 45)
- variable: `np` (line 46)
- variable: `LOGGER` (line 48)
- class: `IdMapMeta` (line 52)
- class: `_ScopeFilterLogInfo` (line 62)
- function: `_log_extra` (line 71)
- function: `_escape_identifier` (line 95)
- class: `_ScopeFilterSpec` (line 165)
- class: `StructureAnnotations` (line 182)
- class: `DuckDBCatalogOptions` (line 192)
- class: `_DuckDBQueryMixin` (line 201)
- class: `_LegacyOptions` (line 485)
- class: `DuckDBCatalog` (line 492)
- function: `_relation_exists` (line 1877)
- function: `relation_exists` (line 1911)
- function: `_file_checksum` (line 1929)
- function: `_parquet_hash` (line 1951)
- function: `ensure_faiss_idmap_view` (line 1979)
- function: `refresh_faiss_idmap_materialized` (line 2026)

## Graph Metrics

- **fan_in**: 11
- **fan_out**: 12
- **cycle_group**: 42

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 47
- recent churn 90: 47

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

- score: 3.39

## Side Effects

- database
- filesystem

## Complexity

- branches: 188
- cyclomatic: 189
- loc: 2126

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
