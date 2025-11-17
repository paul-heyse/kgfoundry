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

## Definitions

- class: `Hit` (line 20)
- class: `PooledHit` (line 30)
- function: `_minmax_norm` (line 39)
- function: `_softmax_norm` (line 50)
- class: `HybridPoolEvaluator` (line 59)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 0
- **cycle_group**: 23

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

Hit, HybridPoolEvaluator, PooledHit

## Doc Health

- **summary**: Feature-normalized hybrid pooling utilities.
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

- score: 1.59

## Side Effects

- none detected

## Complexity

- branches: 11
- cyclomatic: 12
- loc: 142

## Doc Coverage

- `Hit` (class): summary=yes, examples=no — Individual retrieval hit provided to the hybrid pool.
- `PooledHit` (class): summary=yes, examples=no — Result after pooling with per-source component scores.
- `_minmax_norm` (function): summary=no, examples=no
- `_softmax_norm` (function): summary=no, examples=no
- `HybridPoolEvaluator` (class): summary=yes, examples=no — Blend multi-channel hits with configurable normalization and weights.

## Tags

low-coverage, public-api
