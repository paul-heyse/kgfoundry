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
- from **typing** import TYPE_CHECKING, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **kgfoundry_common.logging** import get_logger
- from **(absolute)** import duckdb

## Definitions

- variable: `duckdb` (line 20)
- class: `DuckDBConfig` (line 26)
- class: `_InstrumentedDuckDBConnection` (line 54)
- class: `DuckDBManager` (line 143)
- class: `DuckDBQueryOptions` (line 281)
- class: `DuckDBQueryBuilder` (line 296)

## Graph Metrics

- **fan_in**: 10
- **fan_out**: 2
- **cycle_group**: 12

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 10
- recent churn 90: 10

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

- score: 2.76

## Side Effects

- database
- filesystem

## Complexity

- branches: 51
- cyclomatic: 52
- loc: 488

## Doc Coverage

- `DuckDBConfig` (class): summary=yes, examples=no — Configuration parameters controlling DuckDB connections.
- `_InstrumentedDuckDBConnection` (class): summary=yes, examples=no — Proxy connection that instruments DuckDB execute calls.
- `DuckDBManager` (class): summary=yes, examples=no — Factory for DuckDB connections with consistent pragmas.
- `DuckDBQueryOptions` (class): summary=yes, examples=no — Options controlling DuckDB query generation.
- `DuckDBQueryBuilder` (class): summary=yes, examples=no — Helper for building parameterized DuckDB queries with scope filters.

## Tags

low-coverage, public-api
