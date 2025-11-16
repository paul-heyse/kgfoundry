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
- from **kgfoundry_common.logging** import get_logger
- from **codeintel_rev.io.duckdb_catalog** import StructureAnnotations
- from **codeintel_rev.mcp_server.schemas** import SearchFilterPayload

## Definitions

- variable: `LOGGER` (line 27)
- class: `EmbeddingClient` (line 30)
- class: `IndexConfigLike` (line 38)
- class: `LimitsConfigLike` (line 68)
- class: `SearchSettings` (line 102)
- class: `CatalogLike` (line 116)
- class: `VectorIndex` (line 139)
- class: `SearchFilters` (line 164)
- class: `SearchRequest` (line 249)
- class: `SearchResult` (line 259)
- class: `SearchResponse` (line 272)
- class: `HydrationPayload` (line 282)
- class: `_StageDurations` (line 290)
- class: `SearchDependencies` (line 299)
- class: `FetchRequest` (line 313)
- class: `FetchObjectResult` (line 321)
- class: `FetchResponse` (line 332)
- class: `FetchDependencies` (line 339)
- function: `run_search` (line 346)
- function: `run_fetch` (line 419)
- function: `_normalize_str_list` (line 475)
- function: `_embed_with_metrics` (line 481)
- function: `_run_ann_search` (line 500)
- function: `_hydrate_with_metrics` (line 535)
- function: `_rerank_with_metrics` (line 570)
- function: `_compose_limits` (line 612)
- function: `_embed_query` (line 644)
- function: `_compute_fanout` (line 657)
- function: `_build_runtime_overrides` (line 666)
- function: `_flatten_ids` (line 693)
- function: `_flatten_scores` (line 699)
- function: `_hydrate_chunks` (line 705)
- function: `_build_results` (line 729)
- function: `_matches_symbols` (line 761)
- function: `_build_metadata` (line 768)
- function: `_build_hit_reasons` (line 793)
- function: `_build_title` (line 815)
- function: `_build_url` (line 822)
- function: `_build_snippet` (line 829)
- function: `_truncate_content` (line 837)
- function: `_build_fetch_metadata` (line 845)
- function: `_build_ann_snapshot` (line 856)
- function: `_write_pool_rows` (line 893)
- function: `_build_pool_reason` (line 946)
- function: `_log_search_completion` (line 957)
- function: `_coerce_int` (line 977)
- function: `_string_sequence` (line 992)
- function: `_repair_single_result` (line 998)
- function: `_resolve_snippet` (line 1013)
- function: `_merge_metadata` (line 1023)
- class: `_RepairStats` (line 1053)
- function: `post_search_validate_and_fill` (line 1061)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 6
- **cycle_group**: 113

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 9
- recent churn 90: 9

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

- branches: 106
- cyclomatic: 107
- loc: 1120

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
