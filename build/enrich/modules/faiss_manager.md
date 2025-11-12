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
- from **datetime** import UTC, datetime
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
- from **codeintel_rev.io.duckdb_catalog** import DuckDBCatalog
- from **(absolute)** import pyarrow
- from **(absolute)** import pyarrow.parquet

## Definitions

- variable: `np` (line 52)
- variable: `pa` (line 58)
- variable: `pq` (line 59)
- variable: `LOGGER` (line 61)
- variable: `logger` (line 62)
- class: `_LazyFaissProxy` (line 65)
- variable: `faiss` (line 109)
- function: `_faiss_module` (line 112)
- function: `_has_faiss_gpu_support` (line 123)
- function: `_log_extra` (line 146)
- class: `FAISSRuntimeOptions` (line 164)
- class: `SearchRuntimeOverrides` (line 185)
- class: `_SearchExecutionParams` (line 194)
- class: `_SearchPlan` (line 204)
- class: `_FAISSIdMapMixin` (line 214)
- class: `_FAISSMetadataMixin` (line 342)
- class: `FAISSManager` (line 472)
- function: `_coerce_to_int` (line 2568)
- function: `_configure_direct_map` (line 2591)
- function: `_set_direct_map_type` (line 2599)

## Graph Metrics

- **fan_in**: 7
- **fan_out**: 6
- **cycle_group**: 65

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 36
- recent churn 90: 36

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

FAISSManager

## Doc Health

- **summary**: FAISS manager for GPU-accelerated vector search.
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

## Hotspot

- score: 3.19

## Side Effects

- filesystem

## Complexity

- branches: 200
- cyclomatic: 201
- loc: 2617

## Doc Coverage

- `_LazyFaissProxy` (class): summary=yes, examples=no — Deferred FAISS module loader to avoid import-time side effects.
- `_faiss_module` (function): summary=yes, params=ok, examples=no — Return the lazily imported FAISS module.
- `_has_faiss_gpu_support` (function): summary=yes, params=ok, examples=no — Return ``True`` when FAISS exposes GPU bindings, otherwise ``False``.
- `_log_extra` (function): summary=yes, params=mismatch, examples=no — Build structured logging extras for FAISS manager events.
- `FAISSRuntimeOptions` (class): summary=yes, examples=no — Runtime tuning options passed to :class:`FAISSManager`.
- `SearchRuntimeOverrides` (class): summary=yes, examples=no — Per-search overrides for HNSW/quantizer parameters.
- `_SearchExecutionParams` (class): summary=yes, examples=no — Runtime parameters applied during dual search execution.
- `_SearchPlan` (class): summary=yes, examples=no — Resolved parameters, query buffer, and timeline metadata for a search.
- `_FAISSIdMapMixin` (class): summary=yes, examples=no — Mixin providing ID map export helpers.
- `_FAISSMetadataMixin` (class): summary=yes, examples=no — Mixin for runtime override metadata helpers.

## Tags

low-coverage, public-api
