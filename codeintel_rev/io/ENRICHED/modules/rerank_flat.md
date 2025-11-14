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
- function: `_perform_exact_rerank` (line 16)
- function: `_normalize_queries` (line 125)
- function: `_prepare_candidate_matrix` (line 159)
- function: `_hydrate_embeddings` (line 205)
- function: `_build_candidate_vectors` (line 261)
- function: `_compute_similarity` (line 330)
- function: `_effective_top_k` (line 399)
- function: `_select_topk` (line 449)
- function: `_empty_result` (line 508)
- class: `FlatReranker` (line 554)
- function: `exact_rerank` (line 615)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 78

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 6
- recent churn 90: 6

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

FlatReranker, exact_rerank

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
- loc: 678

## Doc Coverage

- `_perform_exact_rerank` (function): summary=yes, params=ok, examples=no — Hydrate embeddings for candidate ids and compute exact similarities.
- `_normalize_queries` (function): summary=yes, params=ok, examples=no — Normalize query vectors to 2D array format for batch processing.
- `_prepare_candidate_matrix` (function): summary=yes, params=ok, examples=no — Validate and prepare candidate ID matrix for embedding retrieval.
- `_hydrate_embeddings` (function): summary=yes, params=ok, examples=no — Retrieve embeddings from catalog for valid candidate IDs.
- `_build_candidate_vectors` (function): summary=yes, params=ok, examples=no — Assemble candidate embedding vectors from lookup dictionary.
- `_compute_similarity` (function): summary=yes, params=ok, examples=no — Compute batch similarity scores between queries and candidate vectors.
- `_effective_top_k` (function): summary=yes, params=ok, examples=no — Compute effective top-k value bounded by available candidates.
- `_select_topk` (function): summary=yes, params=ok, examples=no — Select top-k candidates by similarity score with efficient partial sorting.
- `_empty_result` (function): summary=yes, params=ok, examples=no — Create sentinel result arrays for empty or failed reranking operations.
- `FlatReranker` (class): summary=yes, examples=no — Rerank ANN candidates using exact similarities from DuckDB embeddings.

## Tags

low-coverage, public-api
