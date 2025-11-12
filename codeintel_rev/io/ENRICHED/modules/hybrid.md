# retrieval/hybrid.py

## Docstring

```
Hybrid retrieval with RRF fusion.

Fuses results from BM25, SPLADE, and FAISS using Reciprocal Rank Fusion.
```

## Imports

- from **__future__** import annotations
- from **dataclasses** import dataclass
- from **typing** import TYPE_CHECKING
- from **collections.abc** import Sequence

## Definitions

- class: `SearchHit` (line 16)
- function: `reciprocal_rank_fusion` (line 54)
- function: `create_hit_list` (line 102)

## Tags

overlay-needed, public-api
