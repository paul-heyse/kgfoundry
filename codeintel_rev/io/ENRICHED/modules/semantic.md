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

- variable: `httpx` (line 55)
- variable: `np` (line 56)
- variable: `SNIPPET_PREVIEW_CHARS` (line 58)
- variable: `COMPONENT_NAME` (line 59)
- variable: `LOGGER` (line 60)
- class: `_ScopeFilterFlags` (line 64)
- class: `_FaissFanout` (line 99)
- class: `_HybridSearchState` (line 107)
- class: `_HybridResult` (line 119)
- class: `_SemanticPipelineResult` (line 130)
- class: `_SemanticPipelineRequest` (line 141)
- class: `_SearchBudget` (line 151)
- class: `_SemanticSearchPlan` (line 161)
- class: `_MethodContext` (line 174)
- class: `_FaissSearchRequest` (line 187)
- function: `semantic_search` (line 199)
- function: `_semantic_search_sync` (line 266)
- function: `_execute_semantic_pipeline` (line 395)
- function: `_clamp_result_limit` (line 530)
- function: `_build_search_budget` (line 559)
- function: `_build_semantic_search_plan` (line 601)
- function: `_calculate_faiss_fanout` (line 672)
- function: `_overfetch_bonus` (line 709)
- function: `_resolve_hybrid_results` (line 740)
- function: `_build_hybrid_result` (line 841)
- function: `_embed_query_or_raise` (line 881)
- function: `_run_faiss_search_or_raise` (line 921)
- function: `_ensure_hydration_success` (line 958)
- function: `_warn_scope_filter_reduction` (line 993)
- function: `_annotate_hybrid_contributions` (line 1031)
- function: `_embed_query` (line 1062)
- function: `_run_faiss_search` (line 1086)
- function: `_normalize_scope_faiss_tuning` (line 1135)
- function: `_hydrate_findings` (line 1200)
- function: `_build_method` (line 1326)
- function: `_make_envelope` (line 1363)
- function: `_observability_links` (line 1416)
- function: `build_observability_links` (line 1448)
- function: `_success_extras` (line 1465)
- function: `_build_response_extras` (line 1489)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 17
- **cycle_group**: 146

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 41
- recent churn 90: 41

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

- score: 3.10

## Side Effects

- filesystem
- network
- subprocess

## Complexity

- branches: 105
- cyclomatic: 106
- loc: 1538

## Doc Coverage

- `_ScopeFilterFlags` (class): summary=yes, examples=no — Aggregated boolean flags describing the active scope filters.
- `_FaissFanout` (class): summary=yes, examples=no — FAISS fan-out plan produced for a semantic search request.
- `_HybridSearchState` (class): summary=yes, examples=no — Encapsulate the outputs of FAISS prior to hybrid re-ranking.
- `_HybridResult` (class): summary=yes, examples=no — Hydration payload returned after hybrid re-ranking.
- `_SemanticPipelineResult` (class): summary=no, examples=no
- `_SemanticPipelineRequest` (class): summary=no, examples=no
- `_SearchBudget` (class): summary=yes, examples=no — Typed representation of the effective limit and metadata.
- `_SemanticSearchPlan` (class): summary=yes, examples=no — Bundled semantic search parameters derived from scope and settings.
- `_MethodContext` (class): summary=yes, examples=no — Inputs required to build method metadata.
- `_FaissSearchRequest` (class): summary=yes, examples=no — Container describing a FAISS search invocation.

## Tags

low-coverage, public-api
