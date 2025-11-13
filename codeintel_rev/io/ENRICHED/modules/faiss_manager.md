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
- from **codeintel_rev.metrics.registry** import FAISS_ANN_LATENCY_SECONDS, FAISS_BUILD_SECONDS_LAST, FAISS_BUILD_TOTAL, FAISS_INDEX_CODE_SIZE_BYTES, FAISS_INDEX_CUVS_ENABLED, FAISS_INDEX_DIM, FAISS_INDEX_GPU_ENABLED, FAISS_INDEX_SIZE_VECTORS, FAISS_POSTFILTER_DENSITY, FAISS_REFINE_KEPT_RATIO, FAISS_REFINE_LATENCY_SECONDS, FAISS_SEARCH_ERRORS_TOTAL, FAISS_SEARCH_LAST_K, FAISS_SEARCH_LAST_MS, FAISS_SEARCH_NPROBE, FAISS_SEARCH_TOTAL, HNSW_SEARCH_EF, set_compile_flags_id, set_factory_id
- from **codeintel_rev.observability.otel** import as_span, record_span_event
- from **codeintel_rev.observability.timeline** import Timeline, current_timeline
- from **codeintel_rev.retrieval.rerank_flat** import FlatReranker
- from **codeintel_rev.telemetry.decorators** import span_context
- from **codeintel_rev.typing** import NDArrayF32, NDArrayI64, gate_import
- from **kgfoundry_common.errors** import VectorSearchError
- from **kgfoundry_common.logging** import get_logger
- from **(absolute)** import faiss
- from **(absolute)** import numpy
- from **codeintel_rev.io.duckdb_catalog** import DuckDBCatalog
- from **(absolute)** import pyarrow
- from **(absolute)** import pyarrow.parquet

## Definitions

- variable: `FaissIndex` (line 60)
- variable: `np` (line 62)
- variable: `FaissIndex` (line 63)
- variable: `pa` (line 69)
- variable: `pq` (line 70)
- variable: `LOGGER` (line 72)
- variable: `logger` (line 73)
- class: `_LazyFaissProxy` (line 76)
- variable: `faiss` (line 120)
- function: `_faiss_module` (line 123)
- function: `_has_faiss_gpu_support` (line 134)
- function: `apply_parameters` (line 150)
- function: `_log_extra` (line 207)
- class: `FAISSRuntimeOptions` (line 225)
- class: `SearchRuntimeOverrides` (line 246)
- class: `_SearchExecutionParams` (line 255)
- class: `_SearchPlan` (line 265)
- class: `_FAISSIdMapMixin` (line 275)
- class: `FAISSManager` (line 453)
- class: `AutoTuner` (line 2868)
- function: `_coerce_to_int` (line 2996)
- function: `_configure_direct_map` (line 3019)
- function: `_set_direct_map_type` (line 3027)

## Graph Metrics

- **fan_in**: 7
- **fan_out**: 8
- **cycle_group**: 67

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 41
- recent churn 90: 41

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

AutoTuner, FAISSManager, apply_parameters

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

- score: 3.29

## Side Effects

- filesystem

## Complexity

- branches: 227
- cyclomatic: 228
- loc: 3045

## Doc Coverage

- `_LazyFaissProxy` (class): summary=yes, examples=no — Deferred FAISS module loader to avoid import-time side effects.
- `_faiss_module` (function): summary=yes, params=ok, examples=no — Return the lazily imported FAISS module.
- `_has_faiss_gpu_support` (function): summary=yes, params=ok, examples=no — Return ``True`` when FAISS exposes GPU bindings, otherwise ``False``.
- `apply_parameters` (function): summary=yes, params=ok, examples=no — Apply a FAISS ParameterSpace string to ``index``.
- `_log_extra` (function): summary=yes, params=mismatch, examples=no — Build structured logging extras for FAISS manager events.
- `FAISSRuntimeOptions` (class): summary=yes, examples=no — Runtime tuning options passed to :class:`FAISSManager`.
- `SearchRuntimeOverrides` (class): summary=yes, examples=no — Per-search overrides for HNSW/quantizer parameters.
- `_SearchExecutionParams` (class): summary=yes, examples=no — Runtime parameters applied during dual search execution.
- `_SearchPlan` (class): summary=yes, examples=no — Resolved parameters, query buffer, and timeline metadata for a search.
- `_FAISSIdMapMixin` (class): summary=yes, examples=no — Mixin providing ID map export helpers.

## Tags

low-coverage, public-api
