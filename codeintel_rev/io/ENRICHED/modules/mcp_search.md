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
- from **typing** import TYPE_CHECKING, Protocol, cast
- from **uuid** import uuid4
- from **(absolute)** import numpy
- from **codeintel_rev.eval.pool_writer** import write_pool
- from **codeintel_rev.io.faiss_manager** import SearchRuntimeOverrides
- from **codeintel_rev.metrics.registry** import MCP_FETCH_LATENCY_SECONDS, MCP_SEARCH_LATENCY_SECONDS, MCP_SEARCH_POSTFILTER_DENSITY
- from **codeintel_rev.retrieval.types** import SearchPoolRow
- from **codeintel_rev.typing** import NDArrayF32, NDArrayI64
- from **kgfoundry_common.errors** import EmbeddingError
- from **kgfoundry_common.logging** import get_logger
- from **codeintel_rev.io.duckdb_catalog** import StructureAnnotations
- from **codeintel_rev.mcp_server.schemas** import SearchFilterPayload
- from **codeintel_rev.observability.timeline** import Timeline

## Definitions

- variable: `Timeline` (line 31)
- variable: `StructureAnnotations` (line 32)
- variable: `SearchFilterPayload` (line 33)
- variable: `LOGGER` (line 37)
- class: `EmbeddingClient` (line 40)
- class: `IndexConfigLike` (line 48)
- class: `LimitsConfigLike` (line 78)
- class: `SearchSettings` (line 112)
- class: `CatalogLike` (line 126)
- class: `VectorIndex` (line 149)
- class: `SearchFilters` (line 174)
- class: `SearchRequest` (line 259)
- class: `SearchResult` (line 269)
- class: `SearchResponse` (line 282)
- class: `HydrationPayload` (line 292)
- class: `SearchDependencies` (line 300)
- class: `FetchRequest` (line 315)
- class: `FetchObjectResult` (line 323)
- class: `FetchResponse` (line 334)
- class: `FetchDependencies` (line 341)
- function: `run_search` (line 349)
- function: `run_fetch` (line 420)
- function: `_normalize_str_list` (line 480)
- function: `_embed_query` (line 486)
- function: `_compute_fanout` (line 499)
- function: `_build_runtime_overrides` (line 508)
- function: `_flatten_ids` (line 535)
- function: `_flatten_scores` (line 541)
- function: `_hydrate_chunks` (line 547)
- function: `_build_results` (line 571)
- function: `_matches_symbols` (line 603)
- function: `_build_metadata` (line 610)
- function: `_build_hit_reasons` (line 635)
- function: `_build_title` (line 657)
- function: `_build_url` (line 664)
- function: `_build_snippet` (line 671)
- function: `_truncate_content` (line 679)
- function: `_build_fetch_metadata` (line 687)
- function: `_write_pool_rows` (line 698)
- function: `_record_postfilter_density` (line 740)
- function: `_log_search_completion` (line 747)
- function: `_coerce_int` (line 767)
- function: `_string_sequence` (line 782)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 8
- **cycle_group**: 121

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 2
- recent churn 90: 2

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

FetchDependencies, FetchObjectResult, FetchRequest, FetchResponse, SearchDependencies, SearchFilters, SearchRequest, SearchResponse, SearchResult, run_fetch, run_search

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

- score: 2.73

## Side Effects

- filesystem

## Complexity

- branches: 66
- cyclomatic: 67
- loc: 801

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
