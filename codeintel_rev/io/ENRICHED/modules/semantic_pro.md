# mcp_server/adapters/semantic_pro.py

## Docstring

```
Two-stage semantic search (CodeRank → optional WARP → optional reranker).
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import asyncio
- from **collections.abc** import Mapping, Sequence
- from **concurrent.futures** import Future, ThreadPoolExecutor
- from **dataclasses** import dataclass, field
- from **pathlib** import Path
- from **time** import perf_counter
- from **typing** import TYPE_CHECKING, Any, TypedDict, cast
- from **codeintel_rev.app.middleware** import get_session_id
- from **codeintel_rev.errors** import RuntimeUnavailableError
- from **codeintel_rev.io.duckdb_catalog** import StructureAnnotations
- from **codeintel_rev.io.hybrid_search** import HybridSearchOptions, HybridSearchTuning
- from **codeintel_rev.io.rerank_coderankllm** import CodeRankListwiseReranker
- from **codeintel_rev.io.warp_engine** import WarpEngine, WarpUnavailableError
- from **codeintel_rev.mcp_server.schemas** import AnswerEnvelope, ExplanationPayload, Finding, MethodInfo, ScopeIn
- from **codeintel_rev.mcp_server.scope_utils** import get_effective_scope
- from **codeintel_rev.rerank.base** import RerankRequest, RerankResult, ScoredDoc
- from **codeintel_rev.rerank.xtr** import XTRReranker
- from **codeintel_rev.retrieval.gating** import StageGateConfig, should_run_secondary_stage
- from **codeintel_rev.retrieval.types** import HybridResultDoc, HybridSearchResult, SearchHit, StageDecision, StageSignals
- from **kgfoundry_common.errors** import EmbeddingError, VectorSearchError
- from **kgfoundry_common.logging** import get_logger
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.config.settings** import CodeRankLLMConfig, RerankConfig, XTRConfig
- from **codeintel_rev.io.xtr_manager** import XTRIndex

## Definitions

- variable: `SNIPPET_PREVIEW_CHARS` (line 45)
- variable: `COMPONENT_NAME` (line 46)
- variable: `RERANK_STAGE_NAME` (line 47)
- variable: `LOGGER` (line 48)
- class: `RerankOptionPayload` (line 51)
- class: `SemanticProOptions` (line 60)
- class: `RerankRuntimeOptions` (line 73)
- class: `RerankPlan` (line 83)
- class: `SemanticProRuntimeOptions` (line 94)
- variable: `WideSearchHandle` (line 106)
- class: `StageOnePlan` (line 110)
- class: `HydrationPlan` (line 121)
- class: `HydrationOutcome` (line 133)
- class: `_SemanticProRunState` (line 141)
- function: `build_runtime_options` (line 167)
- function: `_summarize_options` (line 249)
- function: `semantic_search_pro` (line 262)
- function: `_semantic_search_pro_sync` (line 355)
- function: `_run_coderank_stage` (line 545)
- function: `_maybe_run_warp` (line 607)
- function: `_should_execute_stage_two` (line 630)
- function: `_execute_stage_two` (line 682)
- function: `_run_fusion_stage` (line 709)
- function: `_maybe_apply_rerank_stage` (line 739)
- class: `_RerankOutcome` (line 814)
- function: `_reorder_docs` (line 819)
- function: `_build_rerank_plan` (line 861)
- function: `_resolve_reranker` (line 882)
- function: `_maybe_schedule_xtr_wide` (line 897)
- function: `_resolve_stage_one_outcome` (line 930)
- function: `_run_xtr_wide_stage` (line 1005)
- function: `_calculate_xtr_k` (line 1026)
- function: `_build_extra_channels` (line 1033)
- function: `_safe_int` (line 1053)
- function: `_merge_rrf_weights` (line 1061)
- function: `_run_warp_stage` (line 1077)
- function: `_warp_executor_hits` (line 1100)
- function: `_xtr_rescore_hits` (line 1139)
- function: `_hydrate_records` (line 1182)
- function: `_hydrate_and_rerank_records` (line 1214)
- function: `_maybe_rerank` (line 1336)
- function: `_rerank_gate_decision` (line 1381)
- function: `_build_findings` (line 1398)
- function: `_structure_explanations` (line 1440)
- function: `merge_explainability_into_findings` (line 1470)
- function: `_build_method_explainability` (line 1535)
- function: `_build_method` (line 1602)
- function: `_assemble_extras` (line 1639)
- function: `_make_envelope` (line 1703)
- function: `_clamp_limit` (line 1719)
- function: `_coerce_positive_int` (line 1730)
- function: `_dedupe_preserve_order` (line 1740)
- class: `WarpOutcome` (line 1752)
- class: `FusionRequest` (line 1762)
- class: `MethodContext` (line 1776)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 16
- **cycle_group**: 120

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 21
- recent churn 90: 21

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Two-stage semantic search (CodeRank → optional WARP → optional reranker).
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

- score: 3.18

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 147
- cyclomatic: 148
- loc: 1788

## Doc Coverage

- `RerankOptionPayload` (class): summary=yes, examples=no — User-facing payload for overruling rerank behavior.
- `SemanticProOptions` (class): summary=yes, examples=no — User-facing options for semantic_pro retrieval.
- `RerankRuntimeOptions` (class): summary=yes, examples=no — Runtime overrides for optional reranker stage.
- `RerankPlan` (class): summary=yes, examples=no — Concrete rerank execution plan derived from settings + overrides.
- `SemanticProRuntimeOptions` (class): summary=yes, examples=no — Internal immutable representation of semantic_pro options.
- `StageOnePlan` (class): summary=yes, examples=no — Container for Stage-1 orchestration inputs to reduce argument lists.
- `HydrationPlan` (class): summary=yes, examples=no — Hydration plus rerank inputs passed as a cohesive plan.
- `HydrationOutcome` (class): summary=yes, examples=no — Result of DuckDB hydration and optional LLM rerank.
- `_SemanticProRunState` (class): summary=yes, examples=no — Mutable run state that keeps local variable counts manageable.
- `build_runtime_options` (function): summary=yes, params=ok, examples=yes — Normalize user-supplied options into an immutable dataclass.

## Tags

low-coverage
