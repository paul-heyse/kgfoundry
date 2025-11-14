# retrieval/types.py

## Docstring

```
Shared retrieval dataclasses for multi-stage pipelines.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Mapping, Sequence
- from **dataclasses** import dataclass, field

## Definitions

- variable: `ChunkId` (line 8)
- variable: `FaissRow` (line 9)
- variable: `Distance` (line 10)
- variable: `FactoryString` (line 11)
- class: `SearchHit` (line 15)
- class: `SearchPoolRow` (line 27)
- class: `HybridResultDoc` (line 39)
- class: `HybridSearchResult` (line 47)
- class: `StageSignals` (line 58)
- class: `StageDecision` (line 80)

## Graph Metrics

- **fan_in**: 14
- **fan_out**: 0
- **cycle_group**: 22

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 4
- recent churn 90: 4

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

ChunkId, Distance, FactoryString, FaissRow, HybridResultDoc, HybridSearchResult, SearchHit, SearchPoolRow, StageDecision, StageSignals

## Doc Health

- **summary**: Shared retrieval dataclasses for multi-stage pipelines.
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

- score: 2.05

## Side Effects

- none detected

## Complexity

- branches: 2
- cyclomatic: 3
- loc: 100

## Doc Coverage

- `SearchHit` (class): summary=yes, examples=no — Single retrieval hit emitted by FAISS/BM25/SPLADE/XTR stages.
- `SearchPoolRow` (class): summary=yes, examples=no — Structured row recorded in evaluator pools.
- `HybridResultDoc` (class): summary=yes, examples=no — Final fused result produced by weighted RRF.
- `HybridSearchResult` (class): summary=yes, examples=no — Container for fused docs alongside explainability metadata.
- `StageSignals` (class): summary=yes, examples=no — Signals gathered from a stage for downstream gating decisions.
- `StageDecision` (class): summary=yes, examples=no — Decision emitted by gating logic describing whether to run the stage.

## Tags

low-coverage, public-api, reexport-hub
