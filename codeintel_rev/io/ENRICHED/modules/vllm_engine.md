# io/vllm_engine.py

## Docstring

```
In-process vLLM embedding engine for Stage-0 retrieval.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import os
- from **collections.abc** import Callable, Sequence
- from **contextlib** import suppress
- from **dataclasses** import dataclass, field
- from **typing** import TYPE_CHECKING, Any, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.runtime** import RuntimeCell
- from **codeintel_rev.typing** import NDArrayF32
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
- class: `_InprocessVLLMRuntime` (line 48)
- class: `InprocessVLLMContext` (line 69)
- class: `InprocessVLLMEmbedder` (line 118)

## Graph Metrics

- **fan_in**: 2
- **fan_out**: 4
- **cycle_group**: 15

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 14
- recent churn 90: 14

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

- score: 2.19

## Side Effects

- filesystem

## Complexity

- branches: 16
- cyclomatic: 17
- loc: 271

## Doc Coverage

- `_InprocessVLLMRuntime` (class): summary=yes, examples=no — Mutable runtime backing the frozen embedder.
- `InprocessVLLMContext` (class): summary=yes, examples=no — Dependency providers for in-process vLLM embeddings.
- `InprocessVLLMEmbedder` (class): summary=yes, examples=yes — Embed text batches locally using vLLM.

## Tags

low-coverage, public-api
