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
- from **codeintel_rev.typing** import NDArrayF32
- from **kgfoundry_common.errors** import EmbeddingError, VectorSearchError
- from **kgfoundry_common.logging** import get_logger
- from **(absolute)** import httpx
- from **(absolute)** import numpy
- from **codeintel_rev.app.config_context** import ApplicationContext

## Definitions

- variable: `httpx` (line 39)
- variable: `np` (line 40)
- variable: `SNIPPET_PREVIEW_CHARS` (line 42)
- variable: `COMPONENT_NAME` (line 43)
- variable: `LOGGER` (line 44)
- class: `_ScopeFilterFlags` (line 48)
- class: `_FaissFanout` (line 83)
- class: `_HybridSearchState` (line 91)
- class: `_HybridResult` (line 103)
- class: `_SearchBudget` (line 114)
- class: `_SemanticSearchPlan` (line 123)
- class: `_MethodContext` (line 135)
- class: `_FaissSearchRequest` (line 147)
- function: `semantic_search` (line 158)
- function: `_semantic_search_sync` (line 225)
- function: `_clamp_result_limit` (line 331)
- function: `_build_search_budget` (line 360)
- function: `_build_semantic_search_plan` (line 401)
- function: `_calculate_faiss_fanout` (line 471)
- function: `_overfetch_bonus` (line 508)
- function: `_resolve_hybrid_results` (line 539)
- function: `_build_hybrid_result` (line 640)
- function: `_embed_query_or_raise` (line 680)
- function: `_run_faiss_search_or_raise` (line 720)
- function: `_ensure_hydration_success` (line 757)
- function: `_warn_scope_filter_reduction` (line 792)
- function: `_annotate_hybrid_contributions` (line 830)
- function: `_embed_query` (line 861)
- function: `_run_faiss_search` (line 885)
- function: `_normalize_scope_faiss_tuning` (line 933)
- function: `_hydrate_findings` (line 998)
- function: `_build_method` (line 1112)
- function: `_make_envelope` (line 1149)
- function: `_success_extras` (line 1199)
- function: `_build_response_extras` (line 1223)

## Dependency Graph

- **fan_in**: 0
- **fan_out**: 10
- **cycle_group**: 108

## Declared Exports (__all__)

semantic_search

## Doc Metrics

- **summary**: Semantic search adapter using FAISS GPU and DuckDB.
- has summary: yes
- param parity: yes
- examples present: yes

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Side Effects

- filesystem
- network
- subprocess

## Complexity

- branches: 75
- cyclomatic: 76
- loc: 1271

## Doc Coverage

- `_ScopeFilterFlags` (class): summary=yes, examples=no — Aggregated boolean flags describing the active scope filters.
- `_FaissFanout` (class): summary=yes, examples=no — FAISS fan-out plan produced for a semantic search request.
- `_HybridSearchState` (class): summary=yes, examples=no — Encapsulate the outputs of FAISS prior to hybrid re-ranking.
- `_HybridResult` (class): summary=yes, examples=no — Hydration payload returned after hybrid re-ranking.
- `_SearchBudget` (class): summary=yes, examples=no — Typed representation of the effective limit and metadata.
- `_SemanticSearchPlan` (class): summary=yes, examples=no — Bundled semantic search parameters derived from scope and settings.
- `_MethodContext` (class): summary=yes, examples=no — Inputs required to build method metadata.
- `_FaissSearchRequest` (class): summary=yes, examples=no — Container describing a FAISS search invocation.
- `semantic_search` (function): summary=yes, params=ok, examples=yes — Perform semantic search using embeddings.
- `_semantic_search_sync` (function): summary=no, examples=no

## Tags

public-api
