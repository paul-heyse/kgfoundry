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
- from **(absolute)** import numpy
- from **codeintel_rev.config.settings** import VLLMConfig
- from **codeintel_rev.io.vllm_engine** import InprocessVLLMEmbedder

## Definitions

- function: `_get_numpy` (line 38)
- class: `EmbeddingRequest` (line 74)
- class: `EmbeddingData` (line 102)
- class: `EmbeddingResponse` (line 127)
- class: `VLLMClient` (line 158)
- function: `__init__` (line 209)
- function: `_initialize_local_engine` (line 224)
- function: `_initialize_http_client` (line 233)
- function: `embed_batch` (line 252)
- function: `_embed_batch_http` (line 361)
- function: `embed_single` (line 388)
- function: `embed_chunks` (line 412)
- function: `embed_batch_async` (line 465)
- function: `close` (line 545)
- function: `aclose` (line 569)
- function: `_embed_batch_async_local` (line 582)
- function: `_ensure_async_http_client` (line 593)
- function: `_require_http_client` (line 611)

## Tags

overlay-needed, public-api
