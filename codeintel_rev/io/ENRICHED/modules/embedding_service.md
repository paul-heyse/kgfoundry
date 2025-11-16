# embeddings/embedding_service.py

## Docstring

```
Embedding provider abstractions for chunk ingestion and runtime services.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import hashlib
- from **(absolute)** import queue
- from **(absolute)** import threading
- from **(absolute)** import time
- from **collections.abc** import Callable, Iterable, Iterator, Sequence
- from **concurrent.futures** import Future
- from **contextlib** import contextmanager, suppress
- from **dataclasses** import dataclass
- from **types** import ModuleType, TracebackType
- from **typing** import Any, Protocol, Self, cast, runtime_checkable
- from **codeintel_rev.config.settings** import EmbeddingsConfig, IndexConfig, Settings, VLLMConfig
- from **codeintel_rev.io.vllm_engine** import InprocessVLLMEmbedder
- from **codeintel_rev.typing** import NDArrayF32, gate_import

## Definitions

- variable: `EMBEDDING_RANK` (line 20)
- class: `EmbeddingRuntimeError` (line 23)
- class: `EmbeddingConfigError` (line 27)
- class: `EmbeddingMetadata` (line 32)
- class: `EmbeddingProvider` (line 61)
- function: `_numpy` (line 88)
- function: `_l2_normalize` (line 99)
- class: `_ExecutorJob` (line 132)
- class: `_FailureCounter` (line 137)
- class: `_BatchResultHandler` (line 155)
- class: `_QueueSentinel` (line 211)
- class: `_BoundedBatchExecutor` (line 215)
- class: `_ProviderState` (line 330)
- class: `_ProviderBase` (line 342)
- class: `VLLMProvider` (line 614)
- function: `get_embedding_provider` (line 639)
- class: `HFEmbeddingProvider` (line 728)
- variable: `EmbeddingProviderBase` (line 800)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 3
- **cycle_group**: 47

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 11
- recent churn 90: 11

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Embedding provider abstractions for chunk ingestion and runtime services.
- has summary: yes
- param parity: yes
- examples present: no

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Config References

- embeddings/README.md

## Hotspot

- score: 2.44

## Side Effects

- none detected

## Raises

NotImplementedError

## Complexity

- branches: 62
- cyclomatic: 63
- loc: 801

## Doc Coverage

- `EmbeddingRuntimeError` (class): summary=yes, examples=no — Raised when an embedding provider fails to run.
- `EmbeddingConfigError` (class): summary=yes, examples=no — Raised when embedding configuration is invalid.
- `EmbeddingMetadata` (class): summary=yes, examples=no — Structured metadata describing the active embedding provider.
- `EmbeddingProvider` (class): summary=yes, examples=no — Common surface for embedding providers used across CLIs and services.
- `_numpy` (function): summary=yes, params=ok, examples=no — Return the lazily imported NumPy module for vector ops.
- `_l2_normalize` (function): summary=yes, params=ok, examples=no — Return vectors scaled to unit length along axis 1.
- `_ExecutorJob` (class): summary=no, examples=no
- `_FailureCounter` (class): summary=yes, examples=no — Increment error counters when an exception bubbles out of a context.
- `_BatchResultHandler` (class): summary=yes, examples=no — Resolve futures when a fused batch completes or fails.
- `_QueueSentinel` (class): summary=yes, examples=no — Unique sentinel signaling executor shutdown.

## Tags

low-coverage
