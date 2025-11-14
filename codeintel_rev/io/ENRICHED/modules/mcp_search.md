# retrieval/mcp_search.py

## Docstring

```
Deep-Research compatible search/fetch orchestration helpers.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Mapping, Sequence
- from **dataclasses** import dataclass, replace
- from **pathlib** import Path
- from **time** import perf_counter
- from **typing** import TYPE_CHECKING, Protocol, cast
- from **uuid** import uuid4
- from **(absolute)** import numpy
- from **codeintel_rev.eval.pool_writer** import write_pool
- from **codeintel_rev.io.faiss_manager** import SearchRuntimeOverrides
- from **codeintel_rev.metrics.registry** import MCP_FETCH_LATENCY_SECONDS, MCP_SEARCH_ANN_LATENCY_MS, MCP_SEARCH_HYDRATION_LATENCY_MS, MCP_SEARCH_LATENCY_SECONDS, MCP_SEARCH_POSTFILTER_DENSITY, MCP_SEARCH_RERANK_LATENCY_MS
- from **codeintel_rev.retrieval.types** import SearchPoolRow
- from **codeintel_rev.typing** import NDArrayF32, NDArrayI64
- from **kgfoundry_common.errors** import EmbeddingError
- from **kgfoundry_common.logging** import get_logger
- from **codeintel_rev.io.duckdb_catalog** import StructureAnnotations
- from **codeintel_rev.mcp_server.schemas** import SearchFilterPayload
- from **codeintel_rev.observability.timeline** import Timeline

## Definitions

- variable: `Timeline` (line 34)
- variable: `StructureAnnotations` (line 35)
- variable: `SearchFilterPayload` (line 36)
- variable: `LOGGER` (line 40)
- class: `EmbeddingClient` (line 43)
- class: `IndexConfigLike` (line 51)
- class: `LimitsConfigLike` (line 81)
- class: `SearchSettings` (line 115)
- class: `CatalogLike` (line 129)
- class: `VectorIndex` (line 152)
- class: `SearchFilters` (line 177)
- class: `SearchRequest` (line 262)
- class: `SearchResult` (line 272)
- class: `SearchResponse` (line 285)
- class: `HydrationPayload` (line 295)
- class: `SearchDependencies` (line 303)
- class: `FetchRequest` (line 318)
- class: `FetchObjectResult` (line 326)
- class: `FetchResponse` (line 337)
- class: `FetchDependencies` (line 344)
- function: `run_search` (line 352)
- function: `run_fetch` (line 438)
- function: `_normalize_str_list` (line 498)
- function: `_embed_query` (line 504)
- function: `_compute_fanout` (line 517)
- function: `_build_runtime_overrides` (line 526)
- function: `_flatten_ids` (line 553)
- function: `_flatten_scores` (line 559)
- function: `_hydrate_chunks` (line 565)
- function: `_build_results` (line 589)
- function: `_matches_symbols` (line 621)
- function: `_build_metadata` (line 628)
- function: `_build_hit_reasons` (line 653)
- function: `_build_title` (line 675)
- function: `_build_url` (line 682)
- function: `_build_snippet` (line 689)
- function: `_truncate_content` (line 697)
- function: `_build_fetch_metadata` (line 705)
- function: `_write_pool_rows` (line 716)
- function: `_record_postfilter_density` (line 758)
- function: `_log_search_completion` (line 765)
- function: `_coerce_int` (line 785)
- function: `_string_sequence` (line 800)
- function: `_repair_single_result` (line 806)
- function: `_resolve_snippet` (line 821)
- function: `_merge_metadata` (line 831)
- class: `_RepairStats` (line 861)
- function: `post_search_validate_and_fill` (line 869)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 8
- **cycle_group**: 130

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 4
- recent churn 90: 4

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

FetchDependencies, FetchObjectResult, FetchRequest, FetchResponse, SearchDependencies, SearchFilters, SearchRequest, SearchResponse, SearchResult, post_search_validate_and_fill, run_fetch, run_search

## Doc Health

- **summary**: Deep-Research compatible search/fetch orchestration helpers.
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

- filesystem

## Complexity

- branches: 92
- cyclomatic: 93
- loc: 928

## Doc Coverage

- `EmbeddingClient` (class): summary=yes, examples=no — Protocol describing the minimal embedder surface needed for search.
- `IndexConfigLike` (class): summary=yes, examples=no — PEP 544 view of the index configuration needed by MCP search.
- `LimitsConfigLike` (class): summary=yes, examples=no — PEP 544 view of server limit configuration.
- `SearchSettings` (class): summary=yes, examples=no — Protocol for the subset of :class:`~codeintel_rev.config.settings.Settings`.
- `CatalogLike` (class): summary=yes, examples=no — DuckDB catalog surface used by the MCP tools.
- `VectorIndex` (class): summary=yes, examples=no — FAISS manager surface consumed by MCP search.
- `SearchFilters` (class): summary=yes, examples=no — Normalized filter payload for the MCP search tool.
- `SearchRequest` (class): summary=yes, examples=no — Search invocation parameters.
- `SearchResult` (class): summary=yes, examples=no — Single search result entry.
- `SearchResponse` (class): summary=yes, examples=no — Structured search response returned to MCP adapters.

## Tags

low-coverage, public-api, reexport-hub
