# io/hybrid_search.py

## Docstring

```
Hybrid retrieval utilities combining FAISS, BM25, and SPLADE.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import math
- from **collections.abc** import Callable, Mapping, Sequence
- from **dataclasses** import dataclass
- from **importlib** import import_module
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING, Protocol
- from **codeintel_rev.evaluation.hybrid_pool** import Hit, HybridPoolEvaluator
- from **codeintel_rev.plugins.channels** import Channel, ChannelContext, ChannelError
- from **codeintel_rev.plugins.registry** import ChannelRegistry
- from **codeintel_rev.retrieval.boosters** import RecencyConfig, apply_recency_boost
- from **codeintel_rev.retrieval.gating** import BudgetDecision, StageGateConfig, analyze_query, decide_budgets, describe_budget_decision
- from **codeintel_rev.retrieval.rm3_heuristics** import RM3Heuristics, RM3Params
- from **codeintel_rev.retrieval.types** import HybridResultDoc, HybridSearchResult, SearchHit
- from **codeintel_rev.app.capabilities** import Capabilities
- from **codeintel_rev.app.config_context** import ResolvedPaths
- from **codeintel_rev.config.settings** import Settings, SpladeConfig
- from **codeintel_rev.io.duckdb_manager** import DuckDBManager

## Definitions

- class: `_LuceneHit` (line 33)
- class: `_LuceneSearcher` (line 38)
- class: `BM25Rm3Config` (line 53)
- class: `BM25SearchProvider` (line 62)
- class: `SpladeSearchProvider` (line 170)
- class: `HybridSearchTuning` (line 338)
- class: `HybridSearchOptions` (line 346)
- class: `HybridSearchProviders` (line 356)
- class: `HybridSearchContext` (line 365)
- class: `_MethodStats` (line 375)
- class: `_FusionContext` (line 384)
- class: `_FusionWork` (line 397)
- class: `HybridSearchEngine` (line 410)

## Graph Metrics

- **fan_in**: 5
- **fan_out**: 12
- **cycle_group**: 30

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 32
- recent churn 90: 32

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

BM25SearchProvider, HybridResultDoc, HybridSearchContext, HybridSearchEngine, HybridSearchOptions, HybridSearchProviders, HybridSearchResult, HybridSearchTuning, SpladeSearchProvider

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

- score: 3.13

## Side Effects

- filesystem

## Complexity

- branches: 116
- cyclomatic: 117
- loc: 1097

## Doc Coverage

- `_LuceneHit` (class): summary=no, examples=no
- `_LuceneSearcher` (class): summary=no, examples=no
- `BM25Rm3Config` (class): summary=yes, examples=no — Bundle RM3 parameters and heuristics for BM25 search.
- `BM25SearchProvider` (class): summary=yes, examples=no — Pyserini-backed BM25 searcher with optional RM3 heuristics.
- `SpladeSearchProvider` (class): summary=yes, examples=no — SPLADE query encoder and Lucene impact searcher for learned sparse retrieval.
- `HybridSearchTuning` (class): summary=yes, examples=no — Runtime overrides for FAISS search metadata.
- `HybridSearchOptions` (class): summary=yes, examples=no — Optional knobs influencing hybrid fusion.
- `HybridSearchProviders` (class): summary=yes, examples=no — Optional channel provider overrides for hybrid search.
- `HybridSearchContext` (class): summary=yes, examples=no — Dependency overrides for :class:`HybridSearchEngine`.
- `_MethodStats` (class): summary=no, examples=no

## Tags

low-coverage, public-api
