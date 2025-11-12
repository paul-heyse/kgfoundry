# retrieval/boosters.py

## Docstring

```
Score boosters applied after fusion.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import re
- from **(absolute)** import time
- from **collections.abc** import Callable, Iterable, Mapping, Sequence
- from **dataclasses** import dataclass
- from **typing** import TYPE_CHECKING, Any
- from **codeintel_rev.retrieval.types** import HybridResultDoc
- from **(absolute)** import duckdb
- from **codeintel_rev.io.duckdb_manager** import DuckDBManager
- from **codeintel_rev.io.duckdb_manager** import DuckDBManager
- from **duckdb** import DuckDBPyConnection

## Definitions

- variable: `duckdb` (line 16)
- variable: `DuckDBManagerType` (line 21)
- variable: `DuckDBManager` (line 26)
- variable: `DuckConnection` (line 31)
- class: `RecencyConfig` (line 39)
- function: `_now` (line 50)
- function: `_exp_decay` (line 54)
- function: `_safe_identifier` (line 60)
- function: `_normalize_ids` (line 67)
- function: `_create_recency_view` (line 77)
- function: `_populate_id_table` (line 89)
- function: `_fetch_commit_ts_duckdb` (line 94)
- function: `apply_recency_boost` (line 141)

## Dependency Graph

- **fan_in**: 1
- **fan_out**: 3
- **cycle_group**: 24

## Declared Exports (__all__)

RecencyConfig, apply_recency_boost

## Tags

public-api
