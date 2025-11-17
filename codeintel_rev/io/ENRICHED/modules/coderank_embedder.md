# io/coderank_embedder.py

## Docstring

```
Pooled wrapper around the CodeRank embedding SentenceTransformer.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import threading
- from **collections.abc** import Callable, Iterable, Sequence
- from **dataclasses** import dataclass
- from **typing** import TYPE_CHECKING, Any, ClassVar, Protocol, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.typing** import NDArrayF32, gate_import
- from **(absolute)** import numpy
- from **sentence_transformers** import SentenceTransformer

## Definitions

- variable: `np` (line 17)
- variable: `SentenceTransformer` (line 18)
- class: `SupportsCodeRankSettings` (line 21)
- class: `SentenceEncoderProtocol` (line 55)
- class: `CodeRankEmbedderContext` (line 70)
- class: `CodeRankEmbedder` (line 104)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 2
- **cycle_group**: 110

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 8
- recent churn 90: 8

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Pooled wrapper around the CodeRank embedding SentenceTransformer.
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

- score: 1.71

## Side Effects

- none detected

## Complexity

- branches: 9
- cyclomatic: 10
- loc: 209

## Doc Coverage

- `SupportsCodeRankSettings` (class): summary=yes, examples=no — Protocol describing the minimal settings required by the embedder.
- `SentenceEncoderProtocol` (class): summary=yes, examples=no — Minimal interface required from embedding backends.
- `CodeRankEmbedderContext` (class): summary=yes, examples=no — Dependency providers for the CodeRank embedder.
- `CodeRankEmbedder` (class): summary=yes, examples=no — Encode queries or code snippets with the CodeRank bi-encoder.

## Tags

low-coverage
