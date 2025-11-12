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

- class: `_LazyFaissProxy` (line 55)
- function: `__init__` (line 60)
- function: `module` (line 63)
- function: `__getattr__` (line 76)
- function: `_faiss_module` (line 102)
- function: `_has_faiss_gpu_support` (line 113)
- function: `_log_extra` (line 136)
- class: `FAISSRuntimeOptions` (line 154)
- class: `SearchRuntimeOverrides` (line 175)
- class: `_SearchExecutionParams` (line 184)
- class: `_SearchPlan` (line 194)
- class: `FAISSManager` (line 204)
- function: `__init__` (line 259)
- function: `build_index` (line 307)
- function: `estimate_memory_usage` (line 392)
- function: `add_vectors` (line 456)
- function: `update_index` (line 494)
- function: `_ensure_secondary_index` (line 562)
- function: `_build_primary_contains` (line 574)
- function: `_wrap_bool_contains` (line 597)
- function: `contains` (line 630)
- function: `_wrap_index_contains` (line 652)
- function: `contains` (line 684)
- function: `_build_existing_ids_set` (line 709)
- function: `_collect_unique_indices` (line 726)
- function: `_log_secondary_added` (line 746)
- function: `save_cpu_index` (line 761)
- function: `load_cpu_index` (line 785)
- function: `save_secondary_index` (line 813)
- function: `load_secondary_index` (line 841)
- function: `clone_to_gpu` (line 884)
- function: `search` (line 979)
- function: `_prepare_search_plan` (line 1115)
- function: `get_runtime_tuning` (line 1188)
- function: `apply_runtime_tuning` (line 1215)
- function: `reset_runtime_tuning` (line 1261)
- function: `search_primary` (line 1280)
- function: `_execute_dual_search` (line 1335)
- function: `search_secondary` (line 1397)
- function: `primary_index_impl` (line 1436)
- function: `_merge_results` (line 1449)
- function: `merge_indexes` (line 1514)
- function: `_extract_all_vectors` (line 1606)
- function: `_try_load_cuvs` (line 1672)
- function: `_require_cpu_index` (line 1700)
- function: `get_compile_options` (line 1723)
- function: `_search_with_params` (line 1738)
- function: `autotune` (line 1790)
- function: `_build_adaptive_index` (line 1885)
- function: `_dynamic_nlist` (line 1946)
- function: `_factory_string_for` (line 1952)
- function: `_record_factory_choice` (line 1969)
- function: `_apply_runtime_parameters` (line 1978)
- function: `_maybe_apply_runtime_parameters` (line 2002)
- function: `_sanitize_runtime_overrides` (line 2023)
- function: `_resolve_search_knobs` (line 2057)
- function: `_lookup_override` (line 2070)
- function: `_pick` (line 2077)
- function: `_load_tuned_profile` (line 2130)
- function: `_timed_search_with_params` (line 2154)
- function: `_brute_force_truth_ids` (line 2163)
- function: `_estimate_recall` (line 2172)
- function: `_ensure_2d` (line 2186)
- function: `_refine_with_flat` (line 2192)
- function: `_downcast_index` (line 2223)
- function: `_active_index` (line 2249)
- function: `_coerce_to_int` (line 2270)
- function: `_configure_direct_map` (line 2293)
- function: `_set_direct_map_type` (line 2301)

## Tags

overlay-needed, public-api
