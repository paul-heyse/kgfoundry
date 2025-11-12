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
- class: `IndexManifest` (line 32)
- class: `FAISSDualIndexManager` (line 89)

## Dependency Graph

- **fan_in**: 0
- **fan_out**: 3
- **cycle_group**: 78

## Declared Exports (__all__)

FAISSDualIndexManager, IndexManifest

## Doc Metrics

- **summary**: FAISS dual-index utilities and metadata helpers.
- has summary: yes
- param parity: yes
- examples present: no

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 70
- cyclomatic: 71
- loc: 645

## Doc Coverage

- `IndexManifest` (class): summary=yes, examples=no — Persisted metadata for FAISS dual-index deployments.
- `FAISSDualIndexManager` (class): summary=yes, examples=no — Manage dual FAISS indexes with CPU/GPU coordination.

## Tags

public-api
