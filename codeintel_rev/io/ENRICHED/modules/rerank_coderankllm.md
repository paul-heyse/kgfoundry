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

- class: `CodeRankListwiseReranker` (line 33)
- function: `__init__` (line 41)
- function: `rerank` (line 56)
- function: `_ensure_model` (line 113)
- function: `_build_prompt` (line 143)
- function: `_parse_rankings` (line 151)

## Tags

overlay-needed
