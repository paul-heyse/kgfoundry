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
- from **typing** import TYPE_CHECKING, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **(absolute)** import duckdb

## Definitions

- variable: `duckdb` (line 18)
- class: `DuckDBConfig` (line 24)
- class: `DuckDBManager` (line 52)
- class: `DuckDBQueryOptions` (line 172)
- class: `DuckDBQueryBuilder` (line 182)

## Dependency Graph

- **fan_in**: 9
- **fan_out**: 2
- **cycle_group**: 33

## Declared Exports (__all__)

DuckDBConfig, DuckDBManager, DuckDBQueryBuilder, DuckDBQueryOptions

## Doc Metrics

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

## Hotspot Score

- score: 2.68

## Side Effects

- database
- filesystem

## Complexity

- branches: 43
- cyclomatic: 44
- loc: 347

## Doc Coverage

- `DuckDBConfig` (class): summary=yes, examples=no — Configuration parameters controlling DuckDB connections.
- `DuckDBManager` (class): summary=yes, examples=no — Factory for DuckDB connections with consistent pragmas.
- `DuckDBQueryOptions` (class): summary=yes, examples=no — Options controlling DuckDB query generation.
- `DuckDBQueryBuilder` (class): summary=yes, examples=no — Helper for building parameterized DuckDB queries with scope filters.

## Tags

low-coverage, public-api
