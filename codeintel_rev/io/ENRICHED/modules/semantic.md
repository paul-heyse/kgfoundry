# mcp_server/adapters/semantic.py

## Docstring

```
Semantic search adapter using FAISS and DuckDB.

Implements semantic code search by embedding queries and searching
the FAISS index, then hydrating results from DuckDB.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import asyncio
- from **collections.abc** import Mapping, Sequence
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **time** import perf_counter
- from **typing** import TYPE_CHECKING, Any, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.app.middleware** import get_session_id
- from **codeintel_rev.errors** import CatalogConsistencyError
- from **codeintel_rev.io.duckdb_catalog** import DuckDBCatalog, StructureAnnotations
- from **codeintel_rev.io.faiss_manager** import SearchRuntimeOverrides
- from **codeintel_rev.io.hybrid_search** import HybridSearchOptions, HybridSearchTuning
- from **codeintel_rev.io.vllm_client** import VLLMClient
- from **codeintel_rev.mcp_server.schemas** import AnswerEnvelope, ExplanationPayload, Finding, MethodInfo, ScopeIn
- from **codeintel_rev.mcp_server.scope_utils** import get_effective_scope
- from **codeintel_rev.typing** import NDArrayF32
- from **kgfoundry_common.errors** import EmbeddingError, VectorSearchError
- from **(absolute)** import httpx
- from **(absolute)** import numpy
- from **codeintel_rev.app.config_context** import ApplicationContext

## Definitions

- variable: `httpx` (line 40)
- variable: `np` (line 41)
- variable: `SNIPPET_PREVIEW_CHARS` (line 43)
- variable: `COMPONENT_NAME` (line 44)
- class: `_ScopeFilterFlags` (line 48)
- class: `_FaissFanout` (line 83)
- class: `_HybridSearchState` (line 91)
- class: `_HybridResult` (line 104)
- class: `_SemanticPipelineResult` (line 115)
- class: `_FaissStageResult` (line 126)
- class: `_HydrationOutcome` (line 135)
- class: `_SemanticPipelineRequest` (line 144)
- class: `_SearchBudget` (line 152)
- class: `_SemanticSearchPlan` (line 162)
- class: `_MethodContext` (line 175)
- class: `_FaissSearchRequest` (line 187)
- function: `semantic_search` (line 198)
- function: `_semantic_search_sync` (line 264)
- function: `_execute_semantic_pipeline` (line 330)
- function: `_run_faiss_stage` (line 375)
- function: `_run_hydration_stage` (line 404)
- function: `_clamp_result_limit` (line 443)
- function: `_build_search_budget` (line 472)
- function: `_build_semantic_search_plan` (line 511)
- function: `_calculate_faiss_fanout` (line 565)
- function: `_overfetch_bonus` (line 602)
- function: `_resolve_hybrid_results` (line 633)
- function: `_build_hybrid_result` (line 734)
- function: `_embed_query_or_raise` (line 774)
- function: `_run_faiss_search_or_raise` (line 810)
- function: `_ensure_hydration_success` (line 846)
- function: `_annotate_hybrid_contributions` (line 877)
- function: `_embed_query` (line 908)
- function: `_run_faiss_search` (line 932)
- function: `_normalize_scope_faiss_tuning` (line 981)
- function: `_hydrate_findings` (line 1046)
- function: `_structure_explanations` (line 1164)
- function: `_build_method` (line 1196)
- function: `_make_envelope` (line 1233)
- function: `_success_extras` (line 1282)
- function: `_build_response_extras` (line 1306)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 11
- **cycle_group**: 119

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 50
- recent churn 90: 50

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

semantic_search

## Doc Health

- **summary**: Semantic search adapter using FAISS and DuckDB.
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

- score: 2.88

## Side Effects

- filesystem
- network
- subprocess

## Complexity

- branches: 86
- cyclomatic: 87
- loc: 1354

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
