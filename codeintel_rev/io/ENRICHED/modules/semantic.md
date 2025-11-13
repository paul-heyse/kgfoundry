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
- from **codeintel_rev.observability.otel** import as_span
- from **codeintel_rev.observability.timeline** import Timeline, current_timeline
- from **codeintel_rev.telemetry.context** import telemetry_metadata
- from **codeintel_rev.typing** import NDArrayF32
- from **kgfoundry_common.errors** import EmbeddingError, VectorSearchError
- from **kgfoundry_common.logging** import get_logger
- from **(absolute)** import httpx
- from **(absolute)** import numpy
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.io.duckdb_catalog** import DuckDBCatalog

## Definitions

- variable: `httpx` (line 44)
- variable: `np` (line 45)
- variable: `SNIPPET_PREVIEW_CHARS` (line 47)
- variable: `COMPONENT_NAME` (line 48)
- variable: `LOGGER` (line 49)
- class: `_ScopeFilterFlags` (line 53)
- class: `_FaissFanout` (line 88)
- class: `_HybridSearchState` (line 96)
- class: `_HybridResult` (line 108)
- class: `_SemanticPipelineResult` (line 119)
- class: `_SemanticPipelineRequest` (line 130)
- class: `_SearchBudget` (line 140)
- class: `_SemanticSearchPlan` (line 149)
- class: `_MethodContext` (line 161)
- class: `_FaissSearchRequest` (line 173)
- function: `semantic_search` (line 185)
- function: `_semantic_search_sync` (line 252)
- function: `_execute_semantic_pipeline` (line 348)
- function: `_clamp_result_limit` (line 413)
- function: `_build_search_budget` (line 442)
- function: `_build_semantic_search_plan` (line 483)
- function: `_calculate_faiss_fanout` (line 553)
- function: `_overfetch_bonus` (line 590)
- function: `_resolve_hybrid_results` (line 621)
- function: `_build_hybrid_result` (line 722)
- function: `_embed_query_or_raise` (line 762)
- function: `_run_faiss_search_or_raise` (line 802)
- function: `_ensure_hydration_success` (line 839)
- function: `_warn_scope_filter_reduction` (line 874)
- function: `_annotate_hybrid_contributions` (line 912)
- function: `_embed_query` (line 943)
- function: `_run_faiss_search` (line 967)
- function: `_normalize_scope_faiss_tuning` (line 1016)
- function: `_hydrate_findings` (line 1081)
- function: `_build_method` (line 1207)
- function: `_make_envelope` (line 1244)
- function: `_success_extras` (line 1297)
- function: `_build_response_extras` (line 1321)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 14
- **cycle_group**: 143

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 38
- recent churn 90: 38

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

- score: 2.97

## Side Effects

- filesystem
- network
- subprocess

## Complexity

- branches: 84
- cyclomatic: 85
- loc: 1369

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
