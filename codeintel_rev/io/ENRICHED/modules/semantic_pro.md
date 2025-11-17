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
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.config.settings** import CodeRankLLMConfig, RerankConfig, XTRConfig
- from **codeintel_rev.io.xtr_manager** import XTRIndex

## Definitions

- variable: `SNIPPET_PREVIEW_CHARS` (line 44)
- variable: `COMPONENT_NAME` (line 45)
- variable: `RERANK_STAGE_NAME` (line 46)
- class: `RerankOptionPayload` (line 49)
- class: `SemanticProOptions` (line 58)
- class: `RerankRuntimeOptions` (line 71)
- class: `RerankPlan` (line 81)
- class: `SemanticProRuntimeOptions` (line 92)
- variable: `WideSearchHandle` (line 104)
- class: `StageOnePlan` (line 108)
- class: `HydrationPlan` (line 119)
- class: `HydrationOutcome` (line 131)
- class: `_SemanticProRunState` (line 140)
- function: `build_runtime_options` (line 166)
- function: `_summarize_options` (line 245)
- function: `semantic_search_pro` (line 258)
- function: `_semantic_search_pro_sync` (line 351)
- function: `_run_coderank_stage` (line 488)
- function: `_maybe_run_warp` (line 539)
- function: `_should_execute_stage_two` (line 562)
- function: `_execute_stage_two` (line 598)
- function: `_run_fusion_stage` (line 621)
- function: `_maybe_apply_rerank_stage` (line 644)
- class: `_RerankOutcome` (line 695)
- function: `_reorder_docs` (line 700)
- function: `_build_rerank_plan` (line 742)
- function: `_resolve_reranker` (line 763)
- function: `_maybe_schedule_xtr_wide` (line 778)
- function: `_resolve_stage_one_outcome` (line 807)
- function: `_run_xtr_wide_stage` (line 879)
- function: `_calculate_xtr_k` (line 901)
- function: `_build_extra_channels` (line 908)
- function: `_safe_int` (line 928)
- function: `_merge_rrf_weights` (line 936)
- function: `_run_warp_stage` (line 949)
- function: `_warp_executor_hits` (line 972)
- function: `_xtr_rescore_hits` (line 1004)
- function: `_hydrate_records` (line 1043)
- function: `_hydrate_and_rerank_records` (line 1075)
- function: `_maybe_rerank` (line 1165)
- function: `_rerank_gate_decision` (line 1206)
- function: `_build_findings` (line 1223)
- function: `_structure_explanations` (line 1265)
- function: `merge_explainability_into_findings` (line 1295)
- function: `_build_method_explainability` (line 1360)
- function: `_build_method` (line 1427)
- function: `_assemble_extras` (line 1464)
- function: `_make_envelope` (line 1534)
- function: `_clamp_limit` (line 1550)
- function: `_coerce_positive_int` (line 1561)
- function: `_dedupe_preserve_order` (line 1571)
- class: `WarpOutcome` (line 1583)
- class: `FusionRequest` (line 1593)
- class: `MethodContext` (line 1607)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 16
- **cycle_group**: 122

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 25
- recent churn 90: 25

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

- score: 3.17

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 144
- cyclomatic: 145
- loc: 1619

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
