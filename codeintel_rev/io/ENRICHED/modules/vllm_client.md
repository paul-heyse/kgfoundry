# io/vllm_client.py

## Docstring

```
vLLM embedding client using msgspec for fast serialization.

OpenAI-compatible /v1/embeddings endpoint with batching support.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import asyncio
- from **contextlib** import nullcontext
- from **functools** import lru_cache
- from **importlib** import import_module
- from **time** import perf_counter
- from **types** import ModuleType
- from **typing** import TYPE_CHECKING, cast
- from **(absolute)** import msgspec
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.observability.otel** import as_span, record_span_event
- from **codeintel_rev.observability.semantic_conventions** import Attrs
- from **codeintel_rev.observability.timeline** import current_timeline
- from **codeintel_rev.telemetry.decorators** import span_context
- from **codeintel_rev.telemetry.prom** import EMBED_BATCH_SIZE, EMBED_LATENCY_SECONDS
- from **codeintel_rev.telemetry.steps** import StepEvent, emit_step
- from **codeintel_rev.typing** import NDArrayF32, gate_import
- from **kgfoundry_common.logging** import get_logger
- from **collections.abc** import Sequence
- from **(absolute)** import httpx
- from **codeintel_rev.config.settings** import VLLMConfig
- from **codeintel_rev.io.vllm_engine** import InprocessVLLMEmbedder

## Definitions

- variable: `httpx` (line 36)
- variable: `LOGGER` (line 38)
- function: `_get_numpy` (line 42)
- class: `EmbeddingRequest` (line 78)
- class: `EmbeddingData` (line 106)
- class: `EmbeddingResponse` (line 131)
- class: `VLLMClient` (line 162)

## Graph Metrics

- **fan_in**: 4
- **fan_out**: 10
- **cycle_group**: 78

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 25
- recent churn 90: 25

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

- score: 2.69

## Side Effects

- network
- subprocess

## Complexity

- branches: 32
- cyclomatic: 33
- loc: 658

## Doc Coverage

- `_get_numpy` (function): summary=yes, params=ok, examples=no — Load numpy lazily when embeddings are computed.
- `EmbeddingRequest` (class): summary=yes, examples=no — OpenAI-compatible embedding request payload.
- `EmbeddingData` (class): summary=yes, examples=no — Single embedding result from a batch request.
- `EmbeddingResponse` (class): summary=yes, examples=no — OpenAI-compatible embedding response payload.
- `VLLMClient` (class): summary=yes, examples=yes — vLLM embedding client supporting HTTP or in-process execution.

## Tags

low-coverage, public-api
