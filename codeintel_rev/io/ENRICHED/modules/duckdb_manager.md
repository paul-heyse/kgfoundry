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
- **cycle_group**: 21

## Declared Exports (__all__)

DuckDBConfig, DuckDBManager, DuckDBQueryBuilder, DuckDBQueryOptions

## Tags

public-api
