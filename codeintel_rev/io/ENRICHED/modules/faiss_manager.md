# io/faiss_manager.py

## Docstring

```
FAISS manager for CPU vector search.

Manages adaptive FAISS indexes (Flat, IVFFlat, or IVF-PQ) with CPU persistence.
Index type is automatically selected based on
corpus size for optimal performance.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **(absolute)** import math
- from **collections.abc** import Callable, Mapping, Sequence
- from **contextlib** import suppress
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
- from **(absolute)** import faiss
- from **(absolute)** import numpy
- from **(absolute)** import pyarrow
- from **(absolute)** import pyarrow.parquet

## Definitions

- variable: `FaissIndex` (line 36)
- variable: `np` (line 38)
- variable: `FaissIndex` (line 39)
- variable: `pa` (line 45)
- variable: `pq` (line 46)
- function: `_run_index_search` (line 51)
- class: `_LazyFaissProxy` (line 87)
- variable: `faiss` (line 131)
- function: `_faiss_module` (line 134)
- function: `apply_parameters` (line 145)
- class: `FAISSRuntimeController` (line 195)
- function: `_log_extra` (line 369)
- class: `FAISSRuntimeOptions` (line 387)
- class: `SearchRuntimeOverrides` (line 406)
- class: `RefineSearchConfig` (line 415)
- class: `_TuningOverrides` (line 424)
- class: `_SearchExecutionParams` (line 435)
- class: `_SearchPlan` (line 444)
- class: `_FAISSIdMapMixin` (line 453)
- class: `FAISSManager` (line 632)
- class: `AutoTuner` (line 3083)
- function: `_coerce_to_int` (line 3193)
- function: `_configure_direct_map` (line 3216)
- function: `_set_direct_map_type` (line 3224)
- function: `_wrap_bool_contains` (line 3261)
- function: `_wrap_index_contains` (line 3297)
- function: `_coerce_optional_int` (line 3335)
- function: `_coerce_optional_float` (line 3369)
- function: `_parse_tuning_overrides` (line 3403)
- function: `_persist_tuning_profile` (line 3429)
- function: `_get_compile_options` (line 3438)

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

AutoTuner, FAISSManager, FAISSRuntimeController, apply_parameters

## Doc Health

- **summary**: FAISS manager for CPU vector search.
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

- score: 3.27

## Side Effects

- filesystem

## Complexity

- branches: 231
- cyclomatic: 232
- loc: 3454

## Doc Coverage

- `_run_index_search` (function): summary=yes, params=ok, examples=no — Execute FAISS search and coerce results into typed NumPy arrays.
- `_LazyFaissProxy` (class): summary=yes, examples=no — Deferred FAISS module loader to avoid import-time side effects.
- `_faiss_module` (function): summary=yes, params=ok, examples=no — Return the lazily imported FAISS module.
- `apply_parameters` (function): summary=yes, params=ok, examples=no — Apply a FAISS ParameterSpace string to ``index``.
- `FAISSRuntimeController` (class): summary=yes, examples=no — Encapsulate runtime tuning operations for :class:`FAISSManager`.
- `_log_extra` (function): summary=yes, params=mismatch, examples=no — Build structured logging extras for FAISS manager events.
- `FAISSRuntimeOptions` (class): summary=yes, examples=no — Runtime tuning options passed to :class:`FAISSManager`.
- `SearchRuntimeOverrides` (class): summary=yes, examples=no — Per-search overrides for HNSW/quantizer parameters.
- `RefineSearchConfig` (class): summary=yes, examples=no — Configuration bundle for refine searches.
- `_TuningOverrides` (class): summary=yes, examples=no — Normalized tuning overrides extracted from a profile payload.

## Tags

low-coverage, public-api
