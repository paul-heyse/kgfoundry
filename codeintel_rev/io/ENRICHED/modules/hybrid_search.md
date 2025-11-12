# io/hybrid_search.py

## Docstring

```
Hybrid retrieval utilities combining FAISS, BM25, and SPLADE.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Mapping, Sequence
- from **dataclasses** import dataclass
- from **importlib** import import_module
- from **pathlib** import Path
- from **time** import perf_counter
- from **typing** import TYPE_CHECKING, Protocol
- from **codeintel_rev.evaluation.hybrid_pool** import Hit, HybridPoolEvaluator
- from **codeintel_rev.observability** import metrics
- from **codeintel_rev.observability.timeline** import Timeline, current_timeline
- from **codeintel_rev.plugins.channels** import Channel, ChannelContext, ChannelError
- from **codeintel_rev.plugins.registry** import ChannelRegistry
- from **codeintel_rev.retrieval.boosters** import RecencyConfig, apply_recency_boost
- from **codeintel_rev.retrieval.gating** import BudgetDecision, StageGateConfig, analyze_query, decide_budgets, describe_budget_decision
- from **codeintel_rev.retrieval.rm3_heuristics** import RM3Heuristics, RM3Params
- from **codeintel_rev.retrieval.types** import ChannelHit, HybridResultDoc, HybridSearchResult
- from **kgfoundry_common.logging** import get_logger
- from **codeintel_rev.app.capabilities** import Capabilities
- from **codeintel_rev.app.config_context** import ResolvedPaths
- from **codeintel_rev.config.settings** import Settings, SpladeConfig
- from **codeintel_rev.io.duckdb_manager** import DuckDBManager

## Definitions

- class: `_LuceneHit` (line 42)
- class: `_LuceneSearcher` (line 47)
- function: `set_bm25` (line 48)
- function: `set_rm3` (line 52)
- function: `search` (line 56)
- class: `BM25Rm3Config` (line 62)
- class: `BM25SearchProvider` (line 71)
- function: `__init__` (line 74)
- function: `_create_searcher` (line 99)
- function: `_ensure_rm3_searcher` (line 107)
- function: `_should_use_rm3` (line 123)
- function: `search` (line 132)
- class: `SpladeSearchProvider` (line 161)
- function: `__init__` (line 200)
- function: `search` (line 236)
- function: `_filter_pairs` (line 277)
- function: `_build_bow` (line 290)
- class: `HybridSearchTuning` (line 309)
- class: `HybridSearchOptions` (line 317)
- class: `_MethodStats` (line 326)
- class: `_FusionContext` (line 335)
- class: `_FusionWork` (line 349)
- class: `HybridSearchEngine` (line 363)
- function: `__init__` (line 366)
- function: `_make_stage_gate_config` (line 392)
- function: `_recency_config` (line 423)
- function: `_profile_query` (line 432)
- function: `_rrf_fuse` (line 451)
- function: `_build_debug_bundle` (line 471)
- function: `_fuse_runs` (line 487)
- function: `_apply_extra_channels` (line 528)
- function: `_resolve_active_channels` (line 541)
- function: `_record_fusion_start` (line 545)
- function: `_execute_fusion` (line 563)
- function: `_run_rrf` (line 612)
- function: `_run_pool` (line 635)
- function: `_apply_recency_boost_if_needed` (line 663)
- function: `search` (line 676)
- function: `_gather_channel_hits` (line 726)
- function: `_channel_disabled_reason` (line 798)
- function: `_missing_capabilities` (line 809)
- function: `_collect_channel_hits` (line 818)
- function: `_emit_channel_skip` (line 865)
- function: `_emit_channel_run` (line 875)
- function: `resolve_path` (line 888)
- function: `_build_semantic_channel_hits` (line 907)
- function: `_compute_pool_weights` (line 919)
- function: `_resolve_pool_weights` (line 931)
- function: `_make_pooler` (line 944)
- function: `_select_pooler` (line 954)
- function: `_method_stats` (line 967)
- function: `_flatten_hits_for_pool` (line 982)
- function: `_build_contribution_map` (line 997)
- function: `_compose_method_metadata` (line 1006)

## Tags

overlay-needed, public-api
