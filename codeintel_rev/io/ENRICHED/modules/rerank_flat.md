# retrieval/rerank_flat.py

## Docstring

```
Exact reranking utilities for FAISS candidates.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import numpy
- from **codeintel_rev.io.duckdb_catalog** import DuckDBCatalog
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 10)
- function: `exact_rerank` (line 13)
- function: `_normalize_queries` (line 120)
- function: `_prepare_candidate_matrix` (line 127)
- function: `_hydrate_embeddings` (line 136)
- function: `_build_candidate_vectors` (line 150)
- function: `_compute_similarity` (line 173)
- function: `_effective_top_k` (line 191)
- function: `_select_topk` (line 198)
- function: `_empty_result` (line 212)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 65

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 1
- recent churn 90: 1

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

exact_rerank

## Doc Health

- **summary**: Exact reranking utilities for FAISS candidates.
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

- score: 1.82

## Side Effects

- none detected

## Complexity

- branches: 14
- cyclomatic: 15
- loc: 219

## Doc Coverage

- `exact_rerank` (function): summary=yes, params=ok, examples=no — Hydrate embeddings for candidate ids and compute exact similarities.
- `_normalize_queries` (function): summary=no, examples=no
- `_prepare_candidate_matrix` (function): summary=no, examples=no
- `_hydrate_embeddings` (function): summary=no, examples=no
- `_build_candidate_vectors` (function): summary=no, examples=no
- `_compute_similarity` (function): summary=no, examples=no
- `_effective_top_k` (function): summary=no, examples=no
- `_select_topk` (function): summary=no, examples=no
- `_empty_result` (function): summary=no, examples=no

## Tags

low-coverage, public-api
