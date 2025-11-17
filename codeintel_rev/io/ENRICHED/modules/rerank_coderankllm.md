# io/rerank_coderankllm.py

## Docstring

```
Listwise reranking using the CodeRankLLM checkpoint.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **(absolute)** import threading
- from **collections.abc** import Callable, Sequence
- from **dataclasses** import dataclass
- from **typing** import TYPE_CHECKING, Any, ClassVar, cast
- from **codeintel_rev.typing** import gate_import
- from **transformers** import AutoModelForCausalLM, PreTrainedTokenizerBase

## Definitions

- class: `CoderankLLMRerankerContext` (line 32)
- class: `CodeRankGenerationSettings` (line 76)
- class: `CodeRankListwiseReranker` (line 84)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 111

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 9
- recent churn 90: 9

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Listwise reranking using the CodeRankLLM checkpoint.
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

- score: 1.93

## Side Effects

- none detected

## Complexity

- branches: 21
- cyclomatic: 22
- loc: 208

## Doc Coverage

- `CoderankLLMRerankerContext` (class): summary=yes, examples=no — Dependency providers for CodeRank listwise reranker.
- `CodeRankGenerationSettings` (class): summary=yes, examples=no — Generation parameters for CodeRank listwise reranker.
- `CodeRankListwiseReranker` (class): summary=yes, examples=no — Listwise reranking helper built on CodeRankLLM.

## Tags

low-coverage
