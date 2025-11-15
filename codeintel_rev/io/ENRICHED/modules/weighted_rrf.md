# retrieval/fusion/weighted_rrf.py

## Docstring

```
Weighted reciprocal rank fusion utilities.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Mapping, Sequence
- from **codeintel_rev.retrieval.types** import HybridResultDoc, SearchHit

## Definitions

- function: `fuse_weighted_rrf` (line 10)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 130

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 3
- recent churn 90: 3

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

fuse_weighted_rrf

## Doc Health

- **summary**: Weighted reciprocal rank fusion utilities.
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

- score: 1.57

## Side Effects

- none detected

## Complexity

- branches: 5
- cyclomatic: 6
- loc: 91

## Doc Coverage

- `fuse_weighted_rrf` (function): summary=yes, params=ok, examples=no — Apply weighted RRF across runs and return fused docs plus contributions.

## Tags

low-coverage, public-api
