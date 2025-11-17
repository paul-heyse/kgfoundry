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
- from **codeintel_rev.retrieval.types** import SearchPoolRow
- from **codeintel_rev.typing** import NDArrayF32, NDArrayI64
- from **kgfoundry_common.errors** import EmbeddingError
- from **codeintel_rev.io.duckdb_catalog** import StructureAnnotations
- from **codeintel_rev.mcp_server.schemas** import SearchFilterPayload

## Definitions

- class: `EmbeddingClient` (line 27)
- class: `IndexConfigLike` (line 35)
- class: `LimitsConfigLike` (line 65)
- class: `SearchSettings` (line 99)
- class: `CatalogLike` (line 113)
- class: `VectorRuntime` (line 136)
- class: `VectorIndex` (line 144)
- class: `SearchFilters` (line 170)
- class: `SearchRequest` (line 255)
- class: `SearchResult` (line 265)
- class: `SearchResponse` (line 278)
- class: `HydrationPayload` (line 288)
- class: `_StageDurations` (line 296)
- class: `SearchDependencies` (line 305)
- class: `FetchRequest` (line 319)
- class: `FetchObjectResult` (line 327)
- class: `FetchResponse` (line 338)
- class: `FetchDependencies` (line 345)
- function: `run_search` (line 352)
- function: `run_fetch` (line 422)
- function: `_normalize_str_list` (line 478)
- function: `_embed_with_metrics` (line 484)
- function: `_run_ann_search` (line 502)
- function: `_hydrate_with_metrics` (line 537)
- function: `_rerank_with_metrics` (line 572)
- function: `_compose_limits` (line 614)
- function: `_embed_query` (line 646)
- function: `_compute_fanout` (line 659)
- function: `_build_runtime_overrides` (line 668)
- function: `_flatten_ids` (line 695)
- function: `_flatten_scores` (line 701)
- function: `_hydrate_chunks` (line 707)
- function: `_build_results` (line 731)
- function: `_matches_symbols` (line 763)
- function: `_build_metadata` (line 770)
- function: `_build_hit_reasons` (line 795)
- function: `_build_title` (line 817)
- function: `_build_url` (line 824)
- function: `_build_snippet` (line 831)
- function: `_truncate_content` (line 839)
- function: `_build_fetch_metadata` (line 847)
- function: `_build_ann_snapshot` (line 858)
- function: `_write_pool_rows` (line 895)
- function: `_build_pool_reason` (line 948)
- function: `_coerce_int` (line 959)
- function: `_string_sequence` (line 974)
- function: `_repair_single_result` (line 980)
- function: `_resolve_snippet` (line 995)
- function: `_merge_metadata` (line 1005)
- class: `_RepairStats` (line 1035)
- function: `post_search_validate_and_fill` (line 1043)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 6
- **cycle_group**: 115

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 12
- recent churn 90: 12

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

- score: 2.78

## Side Effects

- filesystem

## Complexity

- branches: 104
- cyclomatic: 105
- loc: 1102

## Doc Coverage

- `EmbeddingClient` (class): summary=yes, examples=no — Protocol describing the minimal embedder surface needed for search.
- `IndexConfigLike` (class): summary=yes, examples=no — PEP 544 view of the index configuration needed by MCP search.
- `LimitsConfigLike` (class): summary=yes, examples=no — PEP 544 view of server limit configuration.
- `SearchSettings` (class): summary=yes, examples=no — Protocol for the subset of :class:`~codeintel_rev.config.settings.Settings`.
- `CatalogLike` (class): summary=yes, examples=no — DuckDB catalog surface used by the MCP tools.
- `VectorRuntime` (class): summary=yes, examples=no — Runtime tuning controls exposed by FAISS managers.
- `VectorIndex` (class): summary=yes, examples=no — FAISS manager surface consumed by MCP search.
- `SearchFilters` (class): summary=yes, examples=no — Normalized filter payload for the MCP search tool.
- `SearchRequest` (class): summary=yes, examples=no — Search invocation parameters.
- `SearchResult` (class): summary=yes, examples=no — Single search result entry.

## Tags

low-coverage, public-api, reexport-hub
