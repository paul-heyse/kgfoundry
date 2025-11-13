# retrieval/hybrid.py

## Docstring

```
Hybrid retrieval with RRF fusion.

Fuses results from BM25, SPLADE, and FAISS using Reciprocal Rank Fusion.
```

## Imports

- from **__future__** import annotations
- from **typing** import TYPE_CHECKING
- from **codeintel_rev.retrieval.types** import SearchHit
- from **collections.abc** import Sequence

## Definitions

- function: `reciprocal_rank_fusion` (line 16)
- function: `create_hit_list` (line 64)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 2
- **cycle_group**: 122

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

SearchHit, create_hit_list, reciprocal_rank_fusion

## Doc Health

- **summary**: Hybrid retrieval with RRF fusion.
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

- score: 1.52

## Side Effects

- none detected

## Complexity

- branches: 4
- cyclomatic: 5
- loc: 96

## Doc Coverage

- `reciprocal_rank_fusion` (function): summary=yes, params=ok, examples=no — Fuse multiple ranked lists using RRF.
- `create_hit_list` (function): summary=yes, params=ok, examples=no — Create SearchHit list from retrieval results.

## Tags

low-coverage, public-api
