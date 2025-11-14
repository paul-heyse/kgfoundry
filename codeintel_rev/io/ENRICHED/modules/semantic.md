# mcp_server/adapters/semantic.py

## Docstring

```
Semantic search adapter using FAISS GPU and DuckDB.

Implements semantic code search by embedding queries and searching
the FAISS index, then hydrating results from DuckDB.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import asyncio
- from **collections.abc** import Mapping, Sequence
- from **contextlib** import nullcontext
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **time** import perf_counter
- from **typing** import TYPE_CHECKING, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.app.middleware** import get_session_id
- from **codeintel_rev.errors** import CatalogConsistencyError
- from **codeintel_rev.io.faiss_manager** import SearchRuntimeOverrides
- from **codeintel_rev.io.hybrid_search** import HybridSearchOptions, HybridSearchTuning
- from **codeintel_rev.io.vllm_client** import VLLMClient
- from **codeintel_rev.mcp_server.common.observability** import Observation, observe_duration
- from **codeintel_rev.mcp_server.schemas** import AnswerEnvelope, Finding, MethodInfo, ScopeIn
- from **codeintel_rev.mcp_server.scope_utils** import get_effective_scope
- from **codeintel_rev.observability.flight_recorder** import build_report_uri
- from **codeintel_rev.observability.otel** import as_span, current_span_id, current_trace_id
- from **codeintel_rev.observability.semantic_conventions** import Attrs, to_label_str
- from **codeintel_rev.observability.timeline** import Timeline, current_timeline
- from **codeintel_rev.telemetry.context** import current_run_id, current_session, telemetry_metadata
- from **codeintel_rev.telemetry.steps** import StepEvent, emit_step
- from **codeintel_rev.typing** import NDArrayF32
- from **kgfoundry_common.errors** import EmbeddingError, VectorSearchError
- from **kgfoundry_common.logging** import get_logger
- from **(absolute)** import httpx
- from **(absolute)** import numpy
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.io.duckdb_catalog** import DuckDBCatalog

## Definitions

- variable: `httpx` (line 56)
- variable: `np` (line 57)
- variable: `SNIPPET_PREVIEW_CHARS` (line 59)
- variable: `COMPONENT_NAME` (line 60)
- variable: `LOGGER` (line 61)
- class: `_ScopeFilterFlags` (line 65)
- class: `_FaissFanout` (line 100)
- class: `_HybridSearchState` (line 108)
- class: `_HybridResult` (line 121)
- class: `_SemanticPipelineResult` (line 132)
- class: `_FaissStageResult` (line 143)
- class: `_HydrationOutcome` (line 152)
- class: `_SemanticPipelineRequest` (line 161)
- class: `_SearchBudget` (line 171)
- class: `_SemanticSearchPlan` (line 181)
- class: `_MethodContext` (line 194)
- class: `_FaissSearchRequest` (line 207)
- function: `semantic_search` (line 219)
- function: `_semantic_search_sync` (line 286)
- function: `_execute_semantic_pipeline` (line 416)
- function: `_run_faiss_stage` (line 494)
- function: `_run_hydration_stage` (line 540)
- function: `_clamp_result_limit` (line 591)
- function: `_build_search_budget` (line 620)
- function: `_build_semantic_search_plan` (line 663)
- function: `_calculate_faiss_fanout` (line 734)
- function: `_overfetch_bonus` (line 771)
- function: `_resolve_hybrid_results` (line 802)
- function: `_build_hybrid_result` (line 904)
- function: `_embed_query_or_raise` (line 944)
- function: `_run_faiss_search_or_raise` (line 984)
- function: `_ensure_hydration_success` (line 1021)
- function: `_warn_scope_filter_reduction` (line 1056)
- function: `_annotate_hybrid_contributions` (line 1094)
- function: `_embed_query` (line 1125)
- function: `_run_faiss_search` (line 1149)
- function: `_normalize_scope_faiss_tuning` (line 1198)
- function: `_hydrate_findings` (line 1263)
- function: `_build_method` (line 1389)
- function: `_make_envelope` (line 1426)
- function: `_observability_links` (line 1479)
- function: `build_observability_links` (line 1511)
- function: `_success_extras` (line 1528)
- function: `_build_response_extras` (line 1552)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 18
- **cycle_group**: 135

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 43
- recent churn 90: 43

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

semantic_search

## Doc Health

- **summary**: Semantic search adapter using FAISS GPU and DuckDB.
- has summary: yes
- param parity: yes
- examples present: yes

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Hotspot

- score: 3.13

## Side Effects

- filesystem
- network
- subprocess

## Complexity

- branches: 105
- cyclomatic: 106
- loc: 1601

## Doc Coverage

- `_ScopeFilterFlags` (class): summary=yes, examples=no — Aggregated boolean flags describing the active scope filters.
- `_FaissFanout` (class): summary=yes, examples=no — FAISS fan-out plan produced for a semantic search request.
- `_HybridSearchState` (class): summary=yes, examples=no — Encapsulate the outputs of FAISS prior to hybrid re-ranking.
- `_HybridResult` (class): summary=yes, examples=no — Hydration payload returned after hybrid re-ranking.
- `_SemanticPipelineResult` (class): summary=no, examples=no
- `_FaissStageResult` (class): summary=yes, examples=no — Outputs from the FAISS stage before hybrid reranking.
- `_HydrationOutcome` (class): summary=yes, examples=no — DuckDB hydration outcome with duration metadata.
- `_SemanticPipelineRequest` (class): summary=no, examples=no
- `_SearchBudget` (class): summary=yes, examples=no — Typed representation of the effective limit and metadata.
- `_SemanticSearchPlan` (class): summary=yes, examples=no — Bundled semantic search parameters derived from scope and settings.

## Tags

low-coverage, public-api
