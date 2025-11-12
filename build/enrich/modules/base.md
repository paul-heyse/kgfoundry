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
- **cycle_group**: 90

## Declared Exports (__all__)

RerankRequest, RerankResult, Reranker, ScoredDoc

## Doc Metrics

- **summary**: Shared reranker interfaces and request/response types.
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

## Hotspot Score

- score: 1.31

## Side Effects

- none detected

## Complexity

- branches: 0
- cyclomatic: 1
- loc: 47

## Doc Coverage

- `ScoredDoc` (class): summary=yes, examples=no — Document identifier + score pair.
- `RerankResult` (class): summary=yes, examples=no — Result emitted by rerankers.
- `RerankRequest` (class): summary=yes, examples=no — Structured rerank invocation.
- `Reranker` (class): summary=yes, examples=no — Protocol implemented by pluggable rerankers.

## Tags

low-coverage, public-api
