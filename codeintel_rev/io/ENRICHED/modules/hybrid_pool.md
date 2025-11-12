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
- function: `__init__` (line 74)
- function: `pool` (line 85)
- function: `_record_pool_metrics` (line 158)

## Tags

overlay-needed, public-api
