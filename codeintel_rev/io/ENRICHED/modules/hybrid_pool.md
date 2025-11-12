# evaluation/hybrid_pool.py

## Docstring

```
Feature-normalized hybrid pooling utilities.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import math
- from **collections.abc** import Iterable, Mapping, Sequence
- from **dataclasses** import dataclass
- from **time** import perf_counter
- from **codeintel_rev.metrics.registry** import HITS_ABOVE_THRESH, HYBRID_LAST_MS, HYBRID_RETRIEVE_TOTAL, POOL_SHARE_BM25, POOL_SHARE_FAISS, POOL_SHARE_SPLADE, POOL_SHARE_XTR, RECALL_EST_AT_K

## Definitions

- class: `Hit` (line 32)
- class: `PooledHit` (line 42)
- function: `_minmax_norm` (line 51)
- function: `_softmax_norm` (line 62)
- class: `HybridPoolEvaluator` (line 71)

## Dependency Graph

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 35

## Declared Exports (__all__)

Hit, HybridPoolEvaluator, PooledHit

## Doc Metrics

- **summary**: Feature-normalized hybrid pooling utilities.
- has summary: yes
- param parity: yes
- examples present: no

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Side Effects

- none detected

## Complexity

- branches: 14
- cyclomatic: 15
- loc: 177

## Doc Coverage

- `Hit` (class): summary=yes, examples=no — Individual retrieval hit provided to the hybrid pool.
- `PooledHit` (class): summary=yes, examples=no — Result after pooling with per-source component scores.
- `_minmax_norm` (function): summary=no, examples=no
- `_softmax_norm` (function): summary=no, examples=no
- `HybridPoolEvaluator` (class): summary=yes, examples=no — Blend multi-channel hits with configurable normalization and weights.

## Tags

public-api
