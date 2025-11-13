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
- from **numbers** import Integral, Real
- from **pathlib** import Path
- from **threading** import RLock
- from **time** import perf_counter
- from **types** import ModuleType
- from **typing** import TYPE_CHECKING, Any, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.errors** import VectorIndexIncompatibleError, VectorIndexStateError
- from **codeintel_rev.io.duckdb_catalog** import DuckDBCatalog
- from **codeintel_rev.metrics.registry** import FAISS_ANN_LATENCY_SECONDS, FAISS_BUILD_SECONDS_LAST, FAISS_BUILD_TOTAL, FAISS_INDEX_CODE_SIZE_BYTES, FAISS_INDEX_CUVS_ENABLED, FAISS_INDEX_DIM, FAISS_INDEX_GPU_ENABLED, FAISS_INDEX_SIZE_VECTORS, FAISS_POSTFILTER_DENSITY, FAISS_REFINE_KEPT_RATIO, FAISS_REFINE_LATENCY_SECONDS, FAISS_SEARCH_ERRORS_TOTAL, FAISS_SEARCH_LAST_K, FAISS_SEARCH_LAST_MS, FAISS_SEARCH_NPROBE, FAISS_SEARCH_TOTAL, HNSW_SEARCH_EF, set_compile_flags_id, set_factory_id
- from **codeintel_rev.observability.otel** import as_span, record_span_event
- from **codeintel_rev.observability.timeline** import Timeline, current_timeline
- from **codeintel_rev.retrieval.rerank_flat** import FlatReranker
- from **codeintel_rev.retrieval.types** import SearchHit
- from **codeintel_rev.telemetry.decorators** import span_context
- from **codeintel_rev.typing** import NDArrayF32, NDArrayI64, gate_import
- from **kgfoundry_common.errors** import VectorSearchError
- from **kgfoundry_common.logging** import get_logger
- from **(absolute)** import faiss
- from **(absolute)** import numpy
- from **(absolute)** import pyarrow
- from **(absolute)** import pyarrow.parquet

## Definitions

- variable: `FaissIndex` (line 62)
- variable: `np` (line 64)
- variable: `FaissIndex` (line 65)
- variable: `pa` (line 71)
- variable: `pq` (line 72)
- variable: `LOGGER` (line 74)
- variable: `logger` (line 75)
- class: `_LazyFaissProxy` (line 78)
- variable: `faiss` (line 122)
- function: `_faiss_module` (line 125)
- function: `_has_faiss_gpu_support` (line 136)
- function: `apply_parameters` (line 152)
- function: `_log_extra` (line 209)
- class: `FAISSRuntimeOptions` (line 227)
- class: `SearchRuntimeOverrides` (line 248)
- class: `RefineSearchConfig` (line 257)
- class: `_TuningOverrides` (line 266)
- class: `_SearchExecutionParams` (line 277)
- class: `_SearchPlan` (line 287)
- class: `_FAISSIdMapMixin` (line 297)
- class: `FAISSManager` (line 474)
- class: `AutoTuner` (line 3607)
- function: `_coerce_to_int` (line 3737)
- function: `_configure_direct_map` (line 3760)
- function: `_set_direct_map_type` (line 3768)
- function: `_wrap_bool_contains` (line 3811)
- function: `_wrap_index_contains` (line 3847)
- function: `_coerce_optional_int` (line 3885)
- function: `_coerce_optional_float` (line 3919)
- function: `_parse_tuning_overrides` (line 3953)
- function: `_persist_tuning_profile` (line 3979)
- function: `_get_compile_options` (line 3991)

## Graph Metrics

- **fan_in**: 8
- **fan_out**: 10
- **cycle_group**: 70

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 44
- recent churn 90: 44

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

- score: 3.39

## Side Effects

- filesystem

## Complexity

- branches: 254
- cyclomatic: 255
- loc: 4008

## Doc Coverage

- `_LazyFaissProxy` (class): summary=yes, examples=no — Deferred FAISS module loader to avoid import-time side effects.
- `_faiss_module` (function): summary=yes, params=ok, examples=no — Return the lazily imported FAISS module.
- `_has_faiss_gpu_support` (function): summary=yes, params=ok, examples=no — Return ``True`` when FAISS exposes GPU bindings, otherwise ``False``.
- `apply_parameters` (function): summary=yes, params=ok, examples=no — Apply a FAISS ParameterSpace string to ``index``.
- `_log_extra` (function): summary=yes, params=mismatch, examples=no — Build structured logging extras for FAISS manager events.
- `FAISSRuntimeOptions` (class): summary=yes, examples=no — Runtime tuning options passed to :class:`FAISSManager`.
- `SearchRuntimeOverrides` (class): summary=yes, examples=no — Per-search overrides for HNSW/quantizer parameters.
- `RefineSearchConfig` (class): summary=yes, examples=no — Configuration bundle for refine searches.
- `_TuningOverrides` (class): summary=yes, examples=no — Normalized tuning overrides extracted from a profile payload.
- `_SearchExecutionParams` (class): summary=yes, examples=no — Runtime parameters applied during dual search execution.

## Tags

low-coverage, public-api
