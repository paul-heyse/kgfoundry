# io/rerank_coderankllm.py

## Docstring

```
Listwise reranking using the CodeRankLLM checkpoint.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **(absolute)** import threading
- from **collections.abc** import Sequence
- from **typing** import TYPE_CHECKING, Any, ClassVar, cast
- from **codeintel_rev.typing** import gate_import
- from **kgfoundry_common.logging** import get_logger
- from **transformers** import AutoModelForCausalLM, PreTrainedTokenizerBase

## Definitions

- variable: `LOGGER` (line 16)
- class: `CodeRankListwiseReranker` (line 33)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 122

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 7
- recent churn 90: 7

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

- score: 1.91

## Side Effects

- none detected

## Complexity

- branches: 20
- cyclomatic: 21
- loc: 174

## Doc Coverage

- `CodeRankListwiseReranker` (class): summary=yes, examples=no — Listwise reranking helper built on CodeRankLLM.

## Tags

low-coverage
