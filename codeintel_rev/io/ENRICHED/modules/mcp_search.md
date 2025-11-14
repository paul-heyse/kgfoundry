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
- from **codeintel_rev.observability.otel** import record_span_event
- from **codeintel_rev.observability.semantic_conventions** import Attrs, to_label_str
- from **codeintel_rev.retrieval.types** import SearchPoolRow
- from **codeintel_rev.telemetry.decorators** import span_context
- from **codeintel_rev.typing** import NDArrayF32, NDArrayI64
- from **kgfoundry_common.errors** import EmbeddingError
- from **kgfoundry_common.logging** import get_logger
- from **codeintel_rev.io.duckdb_catalog** import StructureAnnotations
- from **codeintel_rev.mcp_server.schemas** import SearchFilterPayload
- from **codeintel_rev.observability.timeline** import Timeline

## Definitions

- variable: `Timeline` (line 37)
- variable: `StructureAnnotations` (line 38)
- variable: `SearchFilterPayload` (line 39)
- variable: `LOGGER` (line 43)
- class: `EmbeddingClient` (line 46)
- class: `IndexConfigLike` (line 54)
- class: `LimitsConfigLike` (line 84)
- class: `SearchSettings` (line 118)
- class: `CatalogLike` (line 132)
- class: `VectorIndex` (line 155)
- class: `SearchFilters` (line 180)
- class: `SearchRequest` (line 265)
- class: `SearchResult` (line 275)
- class: `SearchResponse` (line 288)
- class: `HydrationPayload` (line 298)
- class: `SearchDependencies` (line 306)
- class: `FetchRequest` (line 321)
- class: `FetchObjectResult` (line 329)
- class: `FetchResponse` (line 340)
- class: `FetchDependencies` (line 347)
- function: `run_search` (line 355)
- function: `run_fetch` (line 516)
- function: `_normalize_str_list` (line 582)
- function: `_embed_query` (line 588)
- function: `_compute_fanout` (line 610)
- function: `_build_runtime_overrides` (line 619)
- function: `_flatten_ids` (line 646)
- function: `_flatten_scores` (line 652)
- function: `_hydrate_chunks` (line 658)
- function: `_build_results` (line 682)
- function: `_matches_symbols` (line 714)
- function: `_build_metadata` (line 721)
- function: `_build_hit_reasons` (line 746)
- function: `_build_title` (line 768)
- function: `_build_url` (line 775)
- function: `_build_snippet` (line 782)
- function: `_truncate_content` (line 790)
- function: `_build_fetch_metadata` (line 798)
- function: `_write_pool_rows` (line 809)
- function: `_record_postfilter_density` (line 851)
- function: `_log_search_completion` (line 858)
- function: `_coerce_int` (line 878)
- function: `_string_sequence` (line 893)
- function: `_repair_single_result` (line 899)
- function: `_resolve_snippet` (line 914)
- function: `_merge_metadata` (line 924)
- class: `_RepairStats` (line 954)
- function: `post_search_validate_and_fill` (line 962)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 11
- **cycle_group**: 128

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

- score: 2.97

## Side Effects

- filesystem

## Complexity

- branches: 104
- cyclomatic: 105
- loc: 1021

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
