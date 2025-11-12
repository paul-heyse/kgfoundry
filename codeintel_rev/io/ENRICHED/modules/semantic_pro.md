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
- from **codeintel_rev.io.hybrid_search** import ChannelHit, HybridSearchOptions, HybridSearchTuning
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
- from **codeintel_rev.retrieval.types** import HybridResultDoc, HybridSearchResult, StageDecision, StageSignals
- from **kgfoundry_common.errors** import EmbeddingError, VectorSearchError
- from **kgfoundry_common.logging** import get_logger
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.config.settings** import RerankConfig, XTRConfig
- from **codeintel_rev.io.xtr_manager** import XTRIndex

## Definitions

- variable: `SNIPPET_PREVIEW_CHARS` (line 55)
- variable: `COMPONENT_NAME` (line 56)
- variable: `RERANK_STAGE_NAME` (line 57)
- variable: `LOGGER` (line 58)
- class: `RerankOptionPayload` (line 61)
- class: `SemanticProOptions` (line 70)
- class: `RerankRuntimeOptions` (line 83)
- class: `RerankPlan` (line 93)
- class: `SemanticProRuntimeOptions` (line 104)
- variable: `WideSearchHandle` (line 116)
- class: `StageOnePlan` (line 120)
- class: `HydrationPlan` (line 132)
- class: `HydrationOutcome` (line 145)
- function: `build_runtime_options` (line 152)
- function: `_summarize_options` (line 234)
- function: `semantic_search_pro` (line 247)
- function: `_semantic_search_pro_sync` (line 340)
- function: `_run_coderank_stage` (line 492)
- function: `_timed_coderank_stage` (line 548)
- function: `_maybe_run_warp` (line 568)
- function: `_should_execute_stage_two` (line 593)
- function: `_execute_stage_two` (line 647)
- function: `_run_fusion_stage` (line 681)
- function: `_maybe_apply_rerank_stage` (line 707)
- class: `_RerankOutcome` (line 778)
- function: `_reorder_docs` (line 783)
- function: `_emit_rerank_decision` (line 825)
- function: `_build_rerank_plan` (line 831)
- function: `_resolve_reranker` (line 852)
- function: `_maybe_schedule_xtr_wide` (line 867)
- function: `_resolve_stage_one_outcome` (line 900)
- function: `_run_xtr_wide_stage` (line 978)
- function: `_calculate_xtr_k` (line 1010)
- function: `_build_extra_channels` (line 1017)
- function: `_append_budget_notes` (line 1030)
- function: `_safe_int` (line 1045)
- function: `_merge_rrf_weights` (line 1053)
- function: `_run_warp_stage` (line 1069)
- function: `_warp_executor_hits` (line 1092)
- function: `_xtr_rescore_hits` (line 1124)
- function: `_hydrate_records` (line 1163)
- function: `_hydrate_and_rerank_records` (line 1187)
- function: `_maybe_rerank` (line 1329)
- function: `_build_findings` (line 1374)
- function: `merge_explainability_into_findings` (line 1414)
- function: `_build_method_explainability` (line 1479)
- function: `_build_method` (line 1546)
- function: `_assemble_extras` (line 1585)
- function: `_make_envelope` (line 1649)
- function: `_clamp_limit` (line 1665)
- function: `_coerce_positive_int` (line 1676)
- function: `_dedupe_preserve_order` (line 1686)
- class: `WarpOutcome` (line 1698)
- class: `FusionRequest` (line 1709)
- class: `MethodContext` (line 1723)

## Dependency Graph

- **fan_in**: 0
- **fan_out**: 18
- **cycle_group**: 125

## Doc Metrics

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

## Hotspot Score

- score: 3.24

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 154
- cyclomatic: 155
- loc: 1736

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
