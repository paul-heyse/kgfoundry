# io/duckdb_catalog.py

## Docstring

```
DuckDB catalog for querying Parquet chunks.

Provides SQL views over Parquet directories and query helpers for fast
chunk retrieval and joins.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Iterator, Sequence
- from **contextlib** import contextmanager, suppress
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **threading** import Lock
- from **time** import perf_counter
- from **typing** import TYPE_CHECKING, Self, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.io.duckdb_manager** import DuckDBManager, DuckDBQueryBuilder, DuckDBQueryOptions
- from **codeintel_rev.mcp_server.scope_utils** import LANGUAGE_EXTENSIONS, path_matches_glob
- from **codeintel_rev.observability.timeline** import current_timeline
- from **codeintel_rev.typing** import NDArrayF32
- from **kgfoundry_common.logging** import get_logger
- from **kgfoundry_common.prometheus** import build_histogram
- from **(absolute)** import duckdb
- from **(absolute)** import numpy

## Definitions

- class: `_ScopeFilterSpec` (line 65)
- function: `has_complex_globs` (line 76)
- class: `DuckDBCatalog` (line 81)
- function: `__init__` (line 103)
- function: `open` (line 123)
- function: `close` (line 127)
- function: `__enter__` (line 131)
- function: `__exit__` (line 142)
- function: `manager` (line 147)
- function: `_ensure_ready` (line 151)
- function: `connection` (line 163)
- function: `_log_query` (line 175)
- function: `_ensure_views` (line 188)
- function: `_relation_exists` (line 246)
- function: `relation_exists` (line 280)
- function: `query_by_ids` (line 297)
- function: `query_by_filters` (line 364)
- function: `_build_scope_filter_spec` (line 496)
- function: `_apply_complex_glob_filters` (line 557)
- function: `_apply_language_filters` (line 610)
- function: `_observe_scope_filter_duration` (line 648)
- function: `_determine_filter_type` (line 662)
- function: `_is_simple_glob` (line 696)
- function: `get_chunk_by_id` (line 739)
- function: `get_symbols_for_chunk` (line 757)
- function: `query_by_uri` (line 778)
- function: `get_embeddings_by_ids` (line 820)
- function: `count_chunks` (line 881)
- function: `_embedding_dim` (line 901)

## Tags

overlay-needed, public-api
