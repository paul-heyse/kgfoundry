# retrieval/mcp_search.py

## Docstring

```
Deep-Research compatible search/fetch orchestration helpers.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Mapping, Sequence
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **time** import perf_counter
- from **typing** import TYPE_CHECKING, Protocol
- from **uuid** import uuid4
- from **(absolute)** import numpy
- from **codeintel_rev.eval.pool_writer** import PoolRow, write_pool
- from **codeintel_rev.io.faiss_manager** import SearchRuntimeOverrides
- from **codeintel_rev.metrics.registry** import MCP_FETCH_LATENCY_SECONDS, MCP_SEARCH_LATENCY_SECONDS, MCP_SEARCH_POSTFILTER_DENSITY
- from **codeintel_rev.typing** import NDArrayF32, NDArrayI64
- from **kgfoundry_common.errors** import EmbeddingError
- from **kgfoundry_common.logging** import get_logger
- from **codeintel_rev.observability.timeline** import Timeline
- from **codeintel_rev.io.faiss_manager** import SearchRuntimeOverrides

## Definitions

- variable: `Timeline` (line 28)
- variable: `LOGGER` (line 30)
- class: `EmbeddingClient` (line 33)
- class: `IndexConfigLike` (line 40)
- class: `LimitsConfigLike` (line 47)
- class: `SearchSettings` (line 54)
- class: `CatalogLike` (line 61)
- class: `VectorIndex` (line 81)
- class: `SearchFilters` (line 104)
- class: `SearchRequest` (line 169)
- class: `SearchResult` (line 179)
- class: `SearchResponse` (line 192)
- class: `SearchDependencies` (line 202)
- class: `FetchRequest` (line 217)
- class: `FetchObjectResult` (line 225)
- class: `FetchResponse` (line 236)
- class: `FetchDependencies` (line 243)
- function: `run_search` (line 251)
- function: `run_fetch` (line 299)
- function: `_normalize_str_list` (line 336)
- function: `_embed_query` (line 342)
- function: `_compute_fanout` (line 354)
- function: `_build_runtime_overrides` (line 363)
- function: `_flatten_ids` (line 373)
- function: `_flatten_scores` (line 379)
- function: `_hydrate_chunks` (line 385)
- function: `_build_results` (line 405)
- function: `_matches_symbols` (line 437)
- function: `_build_metadata` (line 445)
- function: `_build_hit_reasons` (line 471)
- function: `_build_title` (line 494)
- function: `_build_url` (line 501)
- function: `_build_snippet` (line 508)
- function: `_truncate_content` (line 516)
- function: `_build_fetch_metadata` (line 524)
- function: `_write_pool_rows` (line 535)
- function: `_record_postfilter_density` (line 568)
- function: `_log_search_completion` (line 575)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 5
- **cycle_group**: 121

## Ownership

- bus factor: 0.00
- recent churn 30: 0
- recent churn 90: 0

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

FetchDependencies, FetchObjectResult, FetchRequest, FetchResponse, SearchDependencies, SearchFilters, SearchRequest, SearchResponse, SearchResult, run_fetch, run_search

## Doc Health

- **summary**: Deep-Research compatible search/fetch orchestration helpers.
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

- score: 2.60

## Side Effects

- filesystem

## Complexity

- branches: 69
- cyclomatic: 70
- loc: 608

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
