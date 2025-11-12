# io/vllm_engine.py

## Docstring

```
In-process vLLM embedding engine for Stage-0 retrieval.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import os
- from **collections.abc** import Sequence
- from **dataclasses** import dataclass, field
- from **typing** import TYPE_CHECKING, Any, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.runtime** import RuntimeCell
- from **codeintel_rev.typing** import NDArrayF32
- from **kgfoundry_common.logging** import get_logger
- from **(absolute)** import numpy
- from **(absolute)** import transformers
- from **(absolute)** import vllm
- from **(absolute)** import config
- from **(absolute)** import inputs
- from **transformers** import PreTrainedTokenizerBase
- from **vllm** import LLM
- from **vllm.config** import PoolerConfig
- from **vllm.inputs** import TokensPrompt
- from **codeintel_rev.config.settings** import VLLMConfig

## Definitions

- class: `_InprocessVLLMRuntime` (line 37)
- function: `__init__` (line 42)
- function: `close` (line 46)
- class: `InprocessVLLMEmbedder` (line 60)
- function: `__post_init__` (line 96)
- function: `embed_batch` (line 108)
- function: `close` (line 164)
- function: `_load_tokenizer` (line 168)
- function: `_load_engine` (line 175)
- function: `_initialize_runtime` (line 191)
- function: `_runtime` (line 205)

## Tags

overlay-needed, public-api
