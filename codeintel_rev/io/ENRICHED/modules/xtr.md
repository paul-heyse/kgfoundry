# rerank/xtr.py

## Docstring

```
XTR-backed reranker implementation.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Sequence
- from **codeintel_rev.io.xtr_manager** import XTRIndex
- from **codeintel_rev.rerank.base** import Reranker, RerankRequest, RerankResult

## Definitions

- class: `XTRReranker` (line 13)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 2
- **cycle_group**: 137

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 2
- recent churn 90: 2

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

XTRReranker

## Doc Health

- **summary**: XTR-backed reranker implementation.
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

- score: 1.58

## Side Effects

- none detected

## Complexity

- branches: 3
- cyclomatic: 4
- loc: 74

## Doc Coverage

- `XTRReranker` (class): summary=yes, examples=no — Rerank hits using the XTR MaxSim scorer.

## Tags

low-coverage, public-api
