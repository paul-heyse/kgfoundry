# io/faiss_dual_index.py

## Docstring

```
FAISS dual-index utilities and metadata helpers.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import asyncio
- from **(absolute)** import importlib
- from **(absolute)** import json
- from **contextlib** import suppress
- from **dataclasses** import asdict, dataclass
- from **pathlib** import Path
- from **types** import ModuleType
- from **typing** import TYPE_CHECKING, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.typing** import NDArrayF32, NDArrayI64
- from **kgfoundry_common.logging** import get_logger
- from **(absolute)** import faiss
- from **(absolute)** import numpy
- from **codeintel_rev.config.settings** import IndexConfig

## Definitions

- class: `IndexManifest` (line 32)
- function: `from_file` (line 49)
- function: `to_file` (line 82)
- class: `FAISSDualIndexManager` (line 89)
- function: `__init__` (line 92)
- function: `set_test_indexes` (line 108)
- function: `gpu_enabled` (line 130)
- function: `gpu_disabled_reason` (line 135)
- function: `primary_index` (line 140)
- function: `secondary_index` (line 145)
- function: `manifest` (line 150)
- function: `ensure_ready` (line 154)
- function: `close` (line 197)
- function: `search` (line 208)
- function: `add_incremental` (line 285)
- function: `needs_compaction` (line 376)
- function: `_reset_gpu_state` (line 398)
- function: `_import_faiss` (line 405)
- function: `_load_primary_index` (line 416)
- function: `_load_secondary_index` (line 455)
- function: `_wrap_with_idmap` (line 469)
- function: `_configure_direct_map` (line 478)
- function: `_load_manifest` (line 501)
- function: `try_gpu_clone` (line 516)
- function: `_build_gpu_cloner_options` (line 576)
- function: `_clone_index_to_gpu` (line 595)
- function: `_select_primary_index` (line 631)
- function: `_select_secondary_index` (line 639)

## Tags

overlay-needed, public-api
