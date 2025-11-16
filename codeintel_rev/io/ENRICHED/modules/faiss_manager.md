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
- from **codeintel_rev.retrieval.rerank_flat** import FlatReranker
- from **codeintel_rev.retrieval.types** import SearchHit
- from **codeintel_rev.typing** import NDArrayF32, NDArrayI64, gate_import
- from **kgfoundry_common.errors** import VectorSearchError
- from **kgfoundry_common.logging** import get_logger
- from **(absolute)** import faiss
- from **(absolute)** import numpy
- from **(absolute)** import pyarrow
- from **(absolute)** import pyarrow.parquet

## Definitions

- variable: `FaissIndex` (line 37)
- variable: `np` (line 39)
- variable: `FaissIndex` (line 40)
- variable: `pa` (line 46)
- variable: `pq` (line 47)
- variable: `LOGGER` (line 49)
- variable: `logger` (line 50)
- function: `_run_index_search` (line 54)
- class: `_LazyFaissProxy` (line 90)
- variable: `faiss` (line 134)
- function: `_faiss_module` (line 137)
- function: `_has_faiss_gpu_support` (line 148)
- function: `apply_parameters` (line 164)
- function: `_log_extra` (line 221)
- class: `FAISSRuntimeOptions` (line 239)
- class: `SearchRuntimeOverrides` (line 260)
- class: `RefineSearchConfig` (line 269)
- class: `_TuningOverrides` (line 278)
- class: `_SearchExecutionParams` (line 289)
- class: `_SearchPlan` (line 299)
- class: `_FAISSIdMapMixin` (line 308)
- class: `FAISSManager` (line 495)
- class: `AutoTuner` (line 3441)
- function: `_coerce_to_int` (line 3551)
- function: `_configure_direct_map` (line 3574)
- function: `_set_direct_map_type` (line 3582)
- function: `_wrap_bool_contains` (line 3625)
- function: `_wrap_index_contains` (line 3661)
- function: `_coerce_optional_int` (line 3699)
- function: `_coerce_optional_float` (line 3733)
- function: `_parse_tuning_overrides` (line 3767)
- function: `_persist_tuning_profile` (line 3793)
- function: `_get_compile_options` (line 3805)

## Graph Metrics

- **fan_in**: 8
- **fan_out**: 6
- **cycle_group**: 28

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 50
- recent churn 90: 50

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

- branches: 249
- cyclomatic: 250
- loc: 3821

## Doc Coverage

- `_run_index_search` (function): summary=yes, params=ok, examples=no — Execute FAISS search and coerce results into typed NumPy arrays.
- `_LazyFaissProxy` (class): summary=yes, examples=no — Deferred FAISS module loader to avoid import-time side effects.
- `_faiss_module` (function): summary=yes, params=ok, examples=no — Return the lazily imported FAISS module.
- `_has_faiss_gpu_support` (function): summary=yes, params=ok, examples=no — Return ``True`` when FAISS exposes GPU bindings, otherwise ``False``.
- `apply_parameters` (function): summary=yes, params=ok, examples=no — Apply a FAISS ParameterSpace string to ``index``.
- `_log_extra` (function): summary=yes, params=mismatch, examples=no — Build structured logging extras for FAISS manager events.
- `FAISSRuntimeOptions` (class): summary=yes, examples=no — Runtime tuning options passed to :class:`FAISSManager`.
- `SearchRuntimeOverrides` (class): summary=yes, examples=no — Per-search overrides for HNSW/quantizer parameters.
- `RefineSearchConfig` (class): summary=yes, examples=no — Configuration bundle for refine searches.
- `_TuningOverrides` (class): summary=yes, examples=no — Normalized tuning overrides extracted from a profile payload.

## Tags

low-coverage, public-api
