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
- from **time** import perf_counter
- from **types** import ModuleType
- from **typing** import TYPE_CHECKING, cast
- from **(absolute)** import msgspec
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.observability.otel** import as_span
- from **codeintel_rev.observability.timeline** import current_timeline
- from **codeintel_rev.typing** import NDArrayF32, gate_import
- from **kgfoundry_common.logging** import get_logger
- from **collections.abc** import Sequence
- from **(absolute)** import httpx
- from **codeintel_rev.config.settings** import VLLMConfig
- from **codeintel_rev.io.vllm_engine** import InprocessVLLMEmbedder

## Definitions

- variable: `httpx` (line 31)
- variable: `LOGGER` (line 33)
- function: `_get_numpy` (line 37)
- class: `EmbeddingRequest` (line 73)
- class: `EmbeddingData` (line 101)
- class: `EmbeddingResponse` (line 126)
- class: `VLLMClient` (line 157)

## Dependency Graph

- **fan_in**: 4
- **fan_out**: 6
- **cycle_group**: 36

## Declared Exports (__all__)

EmbeddingData, EmbeddingRequest, EmbeddingResponse, VLLMClient

## Tags

public-api
