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

## Dependency Graph

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 71
