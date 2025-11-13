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
- from **codeintel_rev.io.hybrid_search** import HybridSearchOptions, HybridSearchTuning
- from **codeintel_rev.io.rerank_coderankllm** import CodeRankListwiseReranker
- from **codeintel_rev.io.warp_engine** import WarpEngine, WarpUnavailableError
- from **codeintel_rev.mcp_server.common.observability** import Observation, observe_duration
- from **codeintel_rev.mcp_server.schemas** import AnswerEnvelope, Finding, MethodInfo, ScopeIn, StageInfo
- from **codeintel_rev.mcp_server.scope_utils** import get_effective_scope
- from **codeintel_rev.observability.timeline** import Timeline, current_timeline
- from **codeintel_rev.rerank.base** import RerankRequest, RerankResult, ScoredDoc
- from **codeintel_rev.rerank.xtr** import XTRReranker
- from **codeintel_rev.retrieval.gating** import StageGateConfig, should_run_secondary_stage
- from **codeintel_rev.retrieval.telemetry** import StageTiming, record_stage_decision, record_stage_metric, track_stage
- from **codeintel_rev.retrieval.types** import HybridResultDoc, HybridSearchResult, SearchHit, StageDecision, StageSignals
- from **codeintel_rev.telemetry.context** import telemetry_metadata
- from **kgfoundry_common.errors** import EmbeddingError, VectorSearchError
- from **kgfoundry_common.logging** import get_logger
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.config.settings** import RerankConfig, XTRConfig
- from **codeintel_rev.io.xtr_manager** import XTRIndex

## Definitions

- variable: `SNIPPET_PREVIEW_CHARS` (line 53)
- variable: `COMPONENT_NAME` (line 54)
- variable: `RERANK_STAGE_NAME` (line 55)
- variable: `LOGGER` (line 56)
- class: `RerankOptionPayload` (line 59)
- class: `SemanticProOptions` (line 68)
- class: `RerankRuntimeOptions` (line 81)
- class: `RerankPlan` (line 91)
- class: `SemanticProRuntimeOptions` (line 102)
- variable: `WideSearchHandle` (line 114)
- class: `StageOnePlan` (line 118)
- class: `HydrationPlan` (line 130)
- class: `HydrationOutcome` (line 143)
- function: `build_runtime_options` (line 150)
- function: `_summarize_options` (line 232)
- function: `semantic_search_pro` (line 245)
- function: `_semantic_search_pro_sync` (line 338)
- function: `_run_coderank_stage` (line 490)
- function: `_timed_coderank_stage` (line 546)
- function: `_maybe_run_warp` (line 566)
- function: `_should_execute_stage_two` (line 591)
- function: `_execute_stage_two` (line 645)
- function: `_run_fusion_stage` (line 679)
- function: `_maybe_apply_rerank_stage` (line 705)
- class: `_RerankOutcome` (line 776)
- function: `_reorder_docs` (line 781)
- function: `_emit_rerank_decision` (line 823)
- function: `_build_rerank_plan` (line 829)
- function: `_resolve_reranker` (line 850)
- function: `_maybe_schedule_xtr_wide` (line 865)
- function: `_resolve_stage_one_outcome` (line 898)
- function: `_run_xtr_wide_stage` (line 976)
- function: `_calculate_xtr_k` (line 1008)
- function: `_build_extra_channels` (line 1015)
- function: `_append_budget_notes` (line 1035)
- function: `_safe_int` (line 1050)
- function: `_merge_rrf_weights` (line 1058)
- function: `_run_warp_stage` (line 1074)
- function: `_warp_executor_hits` (line 1097)
- function: `_xtr_rescore_hits` (line 1129)
- function: `_hydrate_records` (line 1168)
- function: `_hydrate_and_rerank_records` (line 1192)
- function: `_maybe_rerank` (line 1334)
- function: `_build_findings` (line 1379)
- function: `merge_explainability_into_findings` (line 1419)
- function: `_build_method_explainability` (line 1484)
- function: `_build_method` (line 1551)
- function: `_assemble_extras` (line 1590)
- function: `_make_envelope` (line 1654)
- function: `_clamp_limit` (line 1673)
- function: `_coerce_positive_int` (line 1684)
- function: `_dedupe_preserve_order` (line 1694)
- class: `WarpOutcome` (line 1706)
- class: `FusionRequest` (line 1717)
- class: `MethodContext` (line 1731)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 19
- **cycle_group**: 145

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 14
- recent churn 90: 14

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

- score: 3.26

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 155
- cyclomatic: 156
- loc: 1744

## Doc Coverage

- `RerankOptionPayload` (class): summary=yes, examples=no — User-facing payload for overruling rerank behavior.
- `SemanticProOptions` (class): summary=yes, examples=no — User-facing options for semantic_pro retrieval.
- `RerankRuntimeOptions` (class): summary=yes, examples=no — Runtime overrides for optional reranker stage.
- `RerankPlan` (class): summary=yes, examples=no — Concrete rerank execution plan derived from settings + overrides.
- `SemanticProRuntimeOptions` (class): summary=yes, examples=no — Internal immutable representation of semantic_pro options.
- `StageOnePlan` (class): summary=yes, examples=no — Container for Stage-1 orchestration inputs to reduce argument lists.
- `HydrationPlan` (class): summary=yes, examples=no — Hydration plus rerank inputs passed as a cohesive plan.
- `HydrationOutcome` (class): summary=yes, examples=no — Result of DuckDB hydration and optional LLM rerank.
- `build_runtime_options` (function): summary=yes, params=ok, examples=yes — Normalize user-supplied options into an immutable dataclass.
- `_summarize_options` (function): summary=no, examples=no

## Tags

low-coverage
