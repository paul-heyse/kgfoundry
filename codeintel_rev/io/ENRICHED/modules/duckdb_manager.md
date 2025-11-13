# io/duckdb_manager.py

## Docstring

```
Thread-safe DuckDB connection manager.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Iterator, Sequence
- from **contextlib** import contextmanager, nullcontext, suppress
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **queue** import Empty, Full, LifoQueue
- from **threading** import Lock
- from **time** import perf_counter
- from **typing** import TYPE_CHECKING, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.observability.otel** import as_span, record_span_event
- from **codeintel_rev.observability.timeline** import current_timeline
- from **(absolute)** import duckdb

## Definitions

- variable: `duckdb` (line 21)
- class: `DuckDBConfig` (line 27)
- class: `_InstrumentedDuckDBConnection` (line 55)
- class: `DuckDBManager` (line 153)
- class: `DuckDBQueryOptions` (line 275)
- class: `DuckDBQueryBuilder` (line 290)

## Graph Metrics

- **fan_in**: 10
- **fan_out**: 4
- **cycle_group**: 51

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 7
- recent churn 90: 7

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

DuckDBConfig, DuckDBManager, DuckDBQueryBuilder, DuckDBQueryOptions

## Doc Health

- **summary**: Thread-safe DuckDB connection manager.
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

- score: 2.83

## Side Effects

- database
- filesystem

## Complexity

- branches: 53
- cyclomatic: 54
- loc: 482

## Doc Coverage

- `DuckDBConfig` (class): summary=yes, examples=no — Configuration parameters controlling DuckDB connections.
- `_InstrumentedDuckDBConnection` (class): summary=yes, examples=no — Proxy connection that instruments DuckDB execute calls.
- `DuckDBManager` (class): summary=yes, examples=no — Factory for DuckDB connections with consistent pragmas.
- `DuckDBQueryOptions` (class): summary=yes, examples=no — Options controlling DuckDB query generation.
- `DuckDBQueryBuilder` (class): summary=yes, examples=no — Helper for building parameterized DuckDB queries with scope filters.

## Tags

low-coverage, public-api
