# io/faiss_manager.py

## Docstring

```
FAISS manager for GPU-accelerated vector search.

Manages adaptive FAISS indexes (Flat, IVFFlat, or IVF-PQ) with cuVS acceleration,
CPU persistence, and GPU cloning. Index type is automatically selected based on
corpus size for optimal performance.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import importlib
- from **(absolute)** import json
- from **(absolute)** import math
- from **collections.abc** import Callable, Mapping, Sequence
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **threading** import RLock
- from **time** import perf_counter
- from **types** import ModuleType
- from **typing** import TYPE_CHECKING, Any, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.metrics.registry** import FAISS_BUILD_SECONDS_LAST, FAISS_BUILD_TOTAL, FAISS_INDEX_CODE_SIZE_BYTES, FAISS_INDEX_CUVS_ENABLED, FAISS_INDEX_DIM, FAISS_INDEX_GPU_ENABLED, FAISS_INDEX_SIZE_VECTORS, FAISS_SEARCH_ERRORS_TOTAL, FAISS_SEARCH_LAST_K, FAISS_SEARCH_LAST_MS, FAISS_SEARCH_NPROBE, FAISS_SEARCH_TOTAL, HNSW_SEARCH_EF, set_compile_flags_id, set_factory_id
- from **codeintel_rev.observability.otel** import as_span
- from **codeintel_rev.observability.timeline** import Timeline, current_timeline
- from **codeintel_rev.typing** import NDArrayF32, NDArrayI64, gate_import
- from **kgfoundry_common.errors** import VectorSearchError
- from **kgfoundry_common.logging** import get_logger
- from **(absolute)** import faiss
- from **(absolute)** import numpy

## Definitions

- variable: `np` (line 49)
- variable: `LOGGER` (line 51)
- variable: `logger` (line 52)
- class: `_LazyFaissProxy` (line 55)
- variable: `faiss` (line 99)
- function: `_faiss_module` (line 102)
- function: `_has_faiss_gpu_support` (line 113)
- function: `_log_extra` (line 136)
- class: `FAISSRuntimeOptions` (line 154)
- class: `SearchRuntimeOverrides` (line 175)
- class: `_SearchExecutionParams` (line 184)
- class: `_SearchPlan` (line 194)
- class: `FAISSManager` (line 204)
- function: `_coerce_to_int` (line 2271)
- function: `_configure_direct_map` (line 2294)
- function: `_set_direct_map_type` (line 2302)

## Dependency Graph

- **fan_in**: 5
- **fan_out**: 5
- **cycle_group**: 37

## Declared Exports (__all__)

FAISSManager

## Tags

public-api
