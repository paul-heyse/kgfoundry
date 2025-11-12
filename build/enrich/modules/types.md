# retrieval/types.py

## Docstring

```
Shared retrieval dataclasses for multi-stage pipelines.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Mapping, Sequence
- from **dataclasses** import dataclass

## Definitions

- class: `ChannelHit` (line 10)
- class: `HybridResultDoc` (line 18)
- class: `HybridSearchResult` (line 26)
- class: `StageSignals` (line 37)
- class: `StageDecision` (line 59)

## Dependency Graph

- **fan_in**: 9
- **fan_out**: 0
- **cycle_group**: 42

## Declared Exports (__all__)

ChannelHit, HybridResultDoc, HybridSearchResult, StageDecision, StageSignals

## Doc Metrics

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

## Hotspot Score

- score: 1.88

## Side Effects

- none detected

## Complexity

- branches: 2
- cyclomatic: 3
- loc: 74

## Doc Coverage

- `ChannelHit` (class): summary=yes, examples=no — Score emitted by a retrieval channel prior to fusion.
- `HybridResultDoc` (class): summary=yes, examples=no — Final fused result produced by weighted RRF.
- `HybridSearchResult` (class): summary=yes, examples=no — Container for fused docs alongside explainability metadata.
- `StageSignals` (class): summary=yes, examples=no — Signals gathered from a stage for downstream gating decisions.
- `StageDecision` (class): summary=yes, examples=no — Decision emitted by gating logic describing whether to run the stage.

## Tags

low-coverage, public-api
