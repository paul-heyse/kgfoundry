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
- from **contextlib** import suppress
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
- from **codeintel_rev.observability.flight_recorder** import build_report_uri
- from **codeintel_rev.observability.otel** import as_span, current_span_id, current_trace_id
- from **codeintel_rev.observability.semantic_conventions** import Attrs, to_label_str
- from **codeintel_rev.observability.timeline** import Timeline, current_timeline
- from **codeintel_rev.rerank.base** import RerankRequest, RerankResult, ScoredDoc
- from **codeintel_rev.rerank.xtr** import XTRReranker
- from **codeintel_rev.retrieval.gating** import StageGateConfig, should_run_secondary_stage
- from **codeintel_rev.retrieval.telemetry** import StageTiming, record_stage_decision, record_stage_metric, track_stage
- from **codeintel_rev.retrieval.types** import HybridResultDoc, HybridSearchResult, SearchHit, StageDecision, StageSignals
- from **codeintel_rev.telemetry.context** import current_run_id, telemetry_metadata
- from **codeintel_rev.telemetry.decorators** import span_context
- from **codeintel_rev.telemetry.steps** import StepEvent, emit_step
- from **kgfoundry_common.errors** import EmbeddingError, VectorSearchError
- from **kgfoundry_common.logging** import get_logger
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.config.settings** import CodeRankLLMConfig, RerankConfig, XTRConfig
- from **codeintel_rev.io.xtr_manager** import XTRIndex

## Definitions

- variable: `SNIPPET_PREVIEW_CHARS` (line 59)
- variable: `COMPONENT_NAME` (line 60)
- variable: `RERANK_STAGE_NAME` (line 61)
- variable: `LOGGER` (line 62)
- class: `RerankOptionPayload` (line 65)
- class: `SemanticProOptions` (line 74)
- class: `RerankRuntimeOptions` (line 87)
- class: `RerankPlan` (line 97)
- class: `SemanticProRuntimeOptions` (line 108)
- variable: `WideSearchHandle` (line 120)
- class: `StageOnePlan` (line 124)
- class: `HydrationPlan` (line 136)
- class: `HydrationOutcome` (line 149)
- function: `build_runtime_options` (line 156)
- function: `_summarize_options` (line 238)
- function: `semantic_search_pro` (line 251)
- function: `_semantic_search_pro_sync` (line 344)
- function: `_run_coderank_stage` (line 539)
- function: `_timed_coderank_stage` (line 607)
- function: `_maybe_run_warp` (line 627)
- function: `_should_execute_stage_two` (line 652)
- function: `_execute_stage_two` (line 706)
- function: `_run_fusion_stage` (line 740)
- function: `_maybe_apply_rerank_stage` (line 774)
- class: `_RerankOutcome` (line 852)
- function: `_reorder_docs` (line 857)
- function: `_emit_rerank_decision` (line 899)
- function: `_build_rerank_plan` (line 905)
- function: `_resolve_reranker` (line 926)
- function: `_maybe_schedule_xtr_wide` (line 941)
- function: `_resolve_stage_one_outcome` (line 974)
- function: `_run_xtr_wide_stage` (line 1052)
- function: `_calculate_xtr_k` (line 1084)
- function: `_build_extra_channels` (line 1091)
- function: `_append_budget_notes` (line 1111)
- function: `_safe_int` (line 1126)
- function: `_merge_rrf_weights` (line 1134)
- function: `_run_warp_stage` (line 1150)
- function: `_warp_executor_hits` (line 1173)
- function: `_xtr_rescore_hits` (line 1214)
- function: `_hydrate_records` (line 1262)
- function: `_hydrate_and_rerank_records` (line 1286)
- function: `_maybe_rerank` (line 1454)
- function: `_rerank_gate_decision` (line 1499)
- function: `_build_findings` (line 1516)
- function: `merge_explainability_into_findings` (line 1556)
- function: `_build_method_explainability` (line 1621)
- function: `_build_method` (line 1688)
- function: `_assemble_extras` (line 1727)
- function: `_make_envelope` (line 1792)
- function: `_observability_links` (line 1811)
- function: `build_observability_links` (line 1838)
- function: `_clamp_limit` (line 1849)
- function: `_coerce_positive_int` (line 1860)
- function: `_dedupe_preserve_order` (line 1870)
- class: `WarpOutcome` (line 1882)
- class: `FusionRequest` (line 1893)
- class: `MethodContext` (line 1907)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 24
- **cycle_group**: 138

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 19
- recent churn 90: 19

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

- score: 3.39

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 178
- cyclomatic: 179
- loc: 1920

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
