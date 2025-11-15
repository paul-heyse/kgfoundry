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

- variable: `LOGGER` (line 39)
- class: `EmbeddingClient` (line 42)
- class: `IndexConfigLike` (line 50)
- class: `LimitsConfigLike` (line 80)
- class: `SearchSettings` (line 114)
- class: `CatalogLike` (line 128)
- class: `VectorIndex` (line 151)
- class: `SearchFilters` (line 176)
- class: `SearchRequest` (line 261)
- class: `SearchResult` (line 271)
- class: `SearchResponse` (line 284)
- class: `HydrationPayload` (line 294)
- class: `_StageDurations` (line 302)
- class: `SearchDependencies` (line 311)
- class: `FetchRequest` (line 326)
- class: `FetchObjectResult` (line 334)
- class: `FetchResponse` (line 345)
- class: `FetchDependencies` (line 352)
- function: `run_search` (line 360)
- function: `run_fetch` (line 458)
- function: `_normalize_str_list` (line 524)
- function: `_build_search_attrs` (line 530)
- function: `_embed_with_metrics` (line 566)
- function: `_run_ann_search` (line 596)
- function: `_hydrate_with_metrics` (line 640)
- function: `_rerank_with_metrics` (line 685)
- function: `_compose_limits` (line 735)
- function: `_embed_query` (line 767)
- function: `_compute_fanout` (line 789)
- function: `_build_runtime_overrides` (line 798)
- function: `_flatten_ids` (line 825)
- function: `_flatten_scores` (line 831)
- function: `_hydrate_chunks` (line 837)
- function: `_build_results` (line 861)
- function: `_matches_symbols` (line 893)
- function: `_build_metadata` (line 900)
- function: `_build_hit_reasons` (line 925)
- function: `_build_title` (line 947)
- function: `_build_url` (line 954)
- function: `_build_snippet` (line 961)
- function: `_truncate_content` (line 969)
- function: `_build_fetch_metadata` (line 977)
- function: `_build_ann_snapshot` (line 988)
- function: `_write_pool_rows` (line 1005)
- function: `_build_pool_reason` (line 1058)
- function: `_record_postfilter_density` (line 1069)
- function: `_log_search_completion` (line 1076)
- function: `_coerce_int` (line 1096)
- function: `_string_sequence` (line 1111)
- function: `_repair_single_result` (line 1117)
- function: `_resolve_snippet` (line 1132)
- function: `_merge_metadata` (line 1142)
- class: `_RepairStats` (line 1172)
- function: `post_search_validate_and_fill` (line 1180)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 11
- **cycle_group**: 135

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 7
- recent churn 90: 7

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

- score: 3.01

## Side Effects

- filesystem

## Complexity

- branches: 119
- cyclomatic: 120
- loc: 1239

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
