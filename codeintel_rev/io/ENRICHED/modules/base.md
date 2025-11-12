# rerank/base.py

## Docstring

```
Shared reranker interfaces and request/response types.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Sequence
- from **dataclasses** import dataclass
- from **typing** import Protocol

## Definitions

- class: `ScoredDoc` (line 13)
- class: `RerankResult` (line 21)
- class: `RerankRequest` (line 29)
- class: `Reranker` (line 38)

## Dependency Graph

- **fan_in**: 2
- **fan_out**: 1
- **cycle_group**: 73

## Declared Exports (__all__)

RerankRequest, RerankResult, Reranker, ScoredDoc

## Tags

public-api
