# io/vllm_client.py

## Docstring

```
vLLM embedding client using msgspec for fast serialization.

OpenAI-compatible /v1/embeddings endpoint with batching support.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import asyncio
- from **functools** import lru_cache
- from **importlib** import import_module
- from **types** import ModuleType
- from **typing** import TYPE_CHECKING, cast
- from **(absolute)** import msgspec
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.typing** import NDArrayF32, gate_import
- from **collections.abc** import Sequence
- from **(absolute)** import httpx
- from **codeintel_rev.config.settings** import VLLMConfig
- from **codeintel_rev.io.vllm_engine** import InprocessVLLMEmbedder

## Definitions

- variable: `httpx` (line 27)
- function: `_get_numpy` (line 31)
- class: `EmbeddingRequest` (line 67)
- class: `EmbeddingData` (line 95)
- class: `EmbeddingResponse` (line 120)
- class: `VLLMClient` (line 151)

## Graph Metrics

- **fan_in**: 4
- **fan_out**: 4
- **cycle_group**: 19

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 35
- recent churn 90: 35

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

EmbeddingData, EmbeddingRequest, EmbeddingResponse, VLLMClient

## Doc Health

- **summary**: vLLM embedding client using msgspec for fast serialization.
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

- score: 2.41

## Side Effects

- network
- subprocess

## Complexity

- branches: 25
- cyclomatic: 26
- loc: 508

## Doc Coverage

- `_get_numpy` (function): summary=yes, params=ok, examples=no — Load numpy lazily when embeddings are computed.
- `EmbeddingRequest` (class): summary=yes, examples=no — OpenAI-compatible embedding request payload.
- `EmbeddingData` (class): summary=yes, examples=no — Single embedding result from a batch request.
- `EmbeddingResponse` (class): summary=yes, examples=no — OpenAI-compatible embedding response payload.
- `VLLMClient` (class): summary=yes, examples=yes — vLLM embedding client supporting HTTP or in-process execution.

## Tags

low-coverage, public-api
