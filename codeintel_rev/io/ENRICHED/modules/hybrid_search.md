# io/hybrid_search.py

## Docstring

```
Hybrid retrieval utilities combining FAISS, BM25, and SPLADE.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import math
- from **collections.abc** import Mapping, Sequence
- from **contextlib** import nullcontext
- from **dataclasses** import dataclass
- from **importlib** import import_module
- from **pathlib** import Path
- from **time** import perf_counter
- from **typing** import TYPE_CHECKING, Protocol
- from **(absolute)** import codeintel_rev.observability.metrics
- from **codeintel_rev.evaluation.hybrid_pool** import Hit, HybridPoolEvaluator
- from **codeintel_rev.observability.otel** import as_span, record_span_event
- from **codeintel_rev.observability.timeline** import Timeline, current_timeline
- from **codeintel_rev.plugins.channels** import Channel, ChannelContext, ChannelError
- from **codeintel_rev.plugins.registry** import ChannelRegistry
- from **codeintel_rev.retrieval.boosters** import RecencyConfig, apply_recency_boost
- from **codeintel_rev.retrieval.gating** import BudgetDecision, StageGateConfig, analyze_query, decide_budgets, describe_budget_decision
- from **codeintel_rev.retrieval.rm3_heuristics** import RM3Heuristics, RM3Params
- from **codeintel_rev.retrieval.types** import HybridResultDoc, HybridSearchResult, SearchHit
- from **codeintel_rev.telemetry.decorators** import span_context
- from **codeintel_rev.telemetry.steps** import StepEvent, emit_step
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
- class: `SpladeSearchProvider` (line 211)
- class: `HybridSearchTuning` (line 423)
- class: `HybridSearchOptions` (line 431)
- class: `_MethodStats` (line 441)
- class: `_FusionContext` (line 450)
- class: `_SearchTelemetryContext` (line 464)
- class: `_FusionWork` (line 470)
- class: `HybridSearchEngine` (line 484)

## Graph Metrics

- **fan_in**: 5
- **fan_out**: 17
- **cycle_group**: 77

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 22
- recent churn 90: 22

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

BM25SearchProvider, HybridResultDoc, HybridSearchEngine, HybridSearchOptions, HybridSearchResult, HybridSearchTuning, SpladeSearchProvider

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

- score: 3.29

## Side Effects

- filesystem

## Complexity

- branches: 140
- cyclomatic: 141
- loc: 1447

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
- `_SearchTelemetryContext` (class): summary=no, examples=no

## Tags

low-coverage, public-api
