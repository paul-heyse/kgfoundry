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

- class: `DuckDBConfig` (line 24)
- class: `DuckDBManager` (line 52)
- function: `__init__` (line 64)
- function: `connection` (line 76)
- function: `config` (line 98)
- function: `connections_created` (line 103)
- function: `close` (line 110)
- function: `__del__` (line 125)
- function: `_create_connection` (line 130)
- function: `_acquire_connection` (line 137)
- function: `_release_connection` (line 157)
- class: `DuckDBQueryOptions` (line 172)
- class: `DuckDBQueryBuilder` (line 182)
- function: `build_filter_query` (line 185)
- function: `_build_where_clauses` (line 275)
- function: `_glob_to_like` (line 324)
- function: `_escape_like_wildcards` (line 345)

## Tags

overlay-needed, public-api
