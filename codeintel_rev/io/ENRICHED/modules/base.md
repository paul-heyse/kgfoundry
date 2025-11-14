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

## Graph Metrics

- **fan_in**: 2
- **fan_out**: 1
- **cycle_group**: 118

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

RerankRequest, RerankResult, Reranker, ScoredDoc

## Doc Health

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

## Hotspot

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
