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

- variable: `np` (line 24)
- variable: `LOGGER` (line 26)
- function: `_run_index_search` (line 31)
- class: `IndexManifest` (line 68)
- class: `FAISSDualIndexManager` (line 125)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 3
- **cycle_group**: 106

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 12
- recent churn 90: 12

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

FAISSDualIndexManager, IndexManifest

## Doc Health

- **summary**: FAISS dual-index utilities and metadata helpers.
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

- score: 2.39

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 72
- cyclomatic: 73
- loc: 681

## Doc Coverage

- `_run_index_search` (function): summary=yes, params=ok, examples=no — Execute FAISS search and coerce outputs into typed NumPy arrays.
- `IndexManifest` (class): summary=yes, examples=no — Persisted metadata for FAISS dual-index deployments.
- `FAISSDualIndexManager` (class): summary=yes, examples=no — Manage dual FAISS indexes with CPU/GPU coordination.

## Tags

low-coverage, public-api
