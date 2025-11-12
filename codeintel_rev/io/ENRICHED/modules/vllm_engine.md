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

- variable: `np` (line 28)
- variable: `transformers` (line 29)
- variable: `vllm` (line 30)
- variable: `vllm_config` (line 31)
- variable: `vllm_inputs` (line 32)
- variable: `LOGGER` (line 34)
- class: `_InprocessVLLMRuntime` (line 37)
- class: `InprocessVLLMEmbedder` (line 60)

## Dependency Graph

- **fan_in**: 1
- **fan_out**: 5
- **cycle_group**: 35

## Declared Exports (__all__)

InprocessVLLMEmbedder

## Tags

public-api
