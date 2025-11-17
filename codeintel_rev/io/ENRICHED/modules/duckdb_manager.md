# io/duckdb_manager.py

## Docstring

```
Thread-safe DuckDB connection manager.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Iterator, Sequence
- from **contextlib** import contextmanager, suppress
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **queue** import Empty, Full, LifoQueue
- from **threading** import Lock
- from **time** import perf_counter
- from **typing** import TYPE_CHECKING, Protocol, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **(absolute)** import duckdb

## Definitions

- variable: `duckdb` (line 19)
- class: `DuckDBConfig` (line 31)
- class: `DuckDBConnector` (line 58)
- class: `DuckDBManagerContext` (line 66)
- class: `_InstrumentedDuckDBConnection` (line 87)
- class: `DuckDBManager` (line 164)
- class: `DuckDBQueryOptions` (line 314)
- class: `DuckDBQueryBuilder` (line 329)

## Graph Metrics

- **fan_in**: 10
- **fan_out**: 2
- **cycle_group**: 7

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 12
- recent churn 90: 12

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

DuckDBConfig, DuckDBManager, DuckDBManagerContext, DuckDBQueryBuilder, DuckDBQueryOptions

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

- score: 2.76

## Side Effects

- database
- filesystem

## Complexity

- branches: 51
- cyclomatic: 52
- loc: 521

## Doc Coverage

- `DuckDBConfig` (class): summary=yes, examples=no — Configuration parameters controlling DuckDB connections.
- `DuckDBConnector` (class): summary=yes, examples=no — Callable protocol describing DuckDB connection factories.
- `DuckDBManagerContext` (class): summary=yes, examples=no — Dependency providers for DuckDBManager.
- `_InstrumentedDuckDBConnection` (class): summary=yes, examples=no — Proxy connection that instruments DuckDB execute calls.
- `DuckDBManager` (class): summary=yes, examples=no — Factory for DuckDB connections with consistent pragmas.
- `DuckDBQueryOptions` (class): summary=yes, examples=no — Options controlling DuckDB query generation.
- `DuckDBQueryBuilder` (class): summary=yes, examples=no — Helper for building parameterized DuckDB queries with scope filters.

## Tags

low-coverage, public-api
