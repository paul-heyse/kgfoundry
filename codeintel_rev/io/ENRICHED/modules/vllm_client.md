# io/vllm_client.py

## Docstring

```
vLLM embedding client using msgspec for fast serialization.

OpenAI-compatible /v1/embeddings endpoint with batching support.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import asyncio
- from **(absolute)** import importlib.util
- from **(absolute)** import logging
- from **(absolute)** import os
- from **collections.abc** import Callable, Sequence
- from **dataclasses** import dataclass
- from **functools** import lru_cache
- from **importlib** import import_module
- from **types** import ModuleType
- from **typing** import TYPE_CHECKING, cast
- from **(absolute)** import msgspec
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.config.settings** import VLLMConfig
- from **codeintel_rev.typing** import NDArrayF32, gate_import
- from **(absolute)** import httpx
- from **codeintel_rev.io.vllm_engine** import InprocessVLLMEmbedder

## Definitions

- variable: `httpx` (line 30)
- variable: `LOGGER` (line 32)
- function: `_truthy_env` (line 35)
- function: `_use_stub_client` (line 41)
- function: `_module_available` (line 45)
- function: `_get_numpy` (line 62)
- function: `_default_http_client_factory` (line 98)
- function: `_default_async_http_client_factory` (line 108)
- function: `_default_inprocess_embedder_factory` (line 118)
- class: `VLLMTransportContext` (line 125)
- class: `EmbeddingRequest` (line 148)
- class: `EmbeddingData` (line 176)
- class: `EmbeddingResponse` (line 201)
- class: `VLLMClient` (line 232)
- class: `_StubVLLMClient` (line 575)
- function: `build_vllm_client` (line 600)

## Graph Metrics

- **fan_in**: 4
- **fan_out**: 4
- **cycle_group**: 16

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 39
- recent churn 90: 39

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

EmbeddingData, EmbeddingRequest, EmbeddingResponse, VLLMClient, build_vllm_client

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

- score: 2.46

## Side Effects

- filesystem
- network
- subprocess

## Complexity

- branches: 30
- cyclomatic: 31
- loc: 631

## Doc Coverage

- `_truthy_env` (function): summary=no, examples=no
- `_use_stub_client` (function): summary=no, examples=no
- `_module_available` (function): summary=yes, params=ok, examples=no — Return ``True`` when ``module_name`` can be imported.
- `_get_numpy` (function): summary=yes, params=ok, examples=no — Load numpy lazily when embeddings are computed.
- `_default_http_client_factory` (function): summary=no, examples=no
- `_default_async_http_client_factory` (function): summary=no, examples=no
- `_default_inprocess_embedder_factory` (function): summary=no, examples=no
- `VLLMTransportContext` (class): summary=yes, examples=no — Dependencies for constructing VLLM transport clients.
- `EmbeddingRequest` (class): summary=yes, examples=no — OpenAI-compatible embedding request payload.
- `EmbeddingData` (class): summary=yes, examples=no — Single embedding result from a batch request.

## Tags

low-coverage, public-api
