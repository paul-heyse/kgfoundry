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
- from **(absolute)** import vllm.config
- from **(absolute)** import vllm.inputs
- from **transformers** import PreTrainedTokenizerBase
- from **vllm** import LLM
- from **vllm.config** import PoolerConfig
- from **vllm.inputs** import TokensPrompt
- from **codeintel_rev.config.settings** import VLLMConfig
- from **(absolute)** import numpy
- from **(absolute)** import transformers
- from **(absolute)** import vllm
- from **(absolute)** import vllm.config
- from **(absolute)** import vllm.inputs

## Definitions

- variable: `np` (line 31)
- variable: `transformers` (line 36)
- variable: `vllm` (line 43)
- variable: `vllm_config` (line 44)
- variable: `vllm_inputs` (line 45)
- variable: `LOGGER` (line 47)
- class: `_InprocessVLLMRuntime` (line 50)
- class: `InprocessVLLMEmbedder` (line 73)

## Graph Metrics

- **fan_in**: 2
- **fan_out**: 4
- **cycle_group**: 33

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 10
- recent churn 90: 10

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

InprocessVLLMEmbedder

## Doc Health

- **summary**: In-process vLLM embedding engine for Stage-0 retrieval.
- has summary: yes
- param parity: yes
- examples present: yes

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Hotspot

- score: 2.16

## Side Effects

- filesystem

## Complexity

- branches: 14
- cyclomatic: 15
- loc: 257

## Doc Coverage

- `_InprocessVLLMRuntime` (class): summary=yes, examples=no — Mutable runtime backing the frozen embedder.
- `InprocessVLLMEmbedder` (class): summary=yes, examples=yes — Embed text batches locally using vLLM.

## Tags

low-coverage, public-api
