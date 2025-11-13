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
- from **(absolute)** import codeintel_rev.observability.metrics
- from **codeintel_rev.evaluation.hybrid_pool** import Hit, HybridPoolEvaluator
- from **codeintel_rev.observability.timeline** import Timeline, current_timeline
- from **codeintel_rev.plugins.channels** import Channel, ChannelContext, ChannelError
- from **codeintel_rev.plugins.registry** import ChannelRegistry
- from **codeintel_rev.retrieval.boosters** import RecencyConfig, apply_recency_boost
- from **codeintel_rev.retrieval.gating** import BudgetDecision, StageGateConfig, analyze_query, decide_budgets, describe_budget_decision
- from **codeintel_rev.retrieval.rm3_heuristics** import RM3Heuristics, RM3Params
- from **codeintel_rev.retrieval.types** import ChannelHit, HybridResultDoc, HybridSearchResult
- from **codeintel_rev.telemetry.decorators** import span_context
- from **kgfoundry_common.logging** import get_logger
- from **codeintel_rev.app.capabilities** import Capabilities
- from **codeintel_rev.app.config_context** import ResolvedPaths
- from **codeintel_rev.config.settings** import Settings, SpladeConfig
- from **codeintel_rev.io.duckdb_manager** import DuckDBManager

## Definitions

- variable: `LOGGER` (line 40)
- class: `_LuceneHit` (line 43)
- class: `_LuceneSearcher` (line 48)
- class: `BM25Rm3Config` (line 63)
- class: `BM25SearchProvider` (line 72)
- class: `SpladeSearchProvider` (line 162)
- class: `HybridSearchTuning` (line 310)
- class: `HybridSearchOptions` (line 318)
- class: `_MethodStats` (line 327)
- class: `_FusionContext` (line 336)
- class: `_FusionWork` (line 350)
- class: `HybridSearchEngine` (line 364)

## Graph Metrics

- **fan_in**: 5
- **fan_out**: 15
- **cycle_group**: 67

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 16
- recent churn 90: 16

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

BM25SearchProvider, ChannelHit, HybridResultDoc, HybridSearchEngine, HybridSearchOptions, HybridSearchResult, HybridSearchTuning, SpladeSearchProvider

## Doc Health

- **summary**: Hybrid retrieval utilities combining FAISS, BM25, and SPLADE.
- has summary: yes
- param parity: yes
- examples present: no

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

## Complexity

- branches: 105
- cyclomatic: 106
- loc: 1067

## Doc Coverage

- `_LuceneHit` (class): summary=no, examples=no
- `_LuceneSearcher` (class): summary=no, examples=no
- `BM25Rm3Config` (class): summary=yes, examples=no — Bundle RM3 parameters and heuristics for BM25 search.
- `BM25SearchProvider` (class): summary=yes, examples=no — Pyserini-backed BM25 searcher with optional RM3 heuristics.
- `SpladeSearchProvider` (class): summary=yes, examples=no — SPLADE query encoder and Lucene impact searcher for learned sparse retrieval.
- `HybridSearchTuning` (class): summary=yes, examples=no — Runtime overrides for FAISS search metadata.
- `HybridSearchOptions` (class): summary=yes, examples=no — Optional knobs influencing hybrid fusion.
- `_MethodStats` (class): summary=no, examples=no
- `_FusionContext` (class): summary=yes, examples=no — All inputs required to fuse dense and sparse channel runs.
- `_FusionWork` (class): summary=yes, examples=no — Resolved fusion parameters after pooler/weights are selected.

## Tags

low-coverage, public-api
