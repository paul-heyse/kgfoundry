# indexing/index_lifecycle.py

## Docstring

```
Index lifecycle management for FAISS/DuckDB/SCIP artifacts.

This module provides a small, platform-agnostic manager that stages new index
versions, publishes them atomically, and exposes helpers used by the FastAPI
app, CLI, and admin endpoints. Versions are stored under a common ``base_dir``
with the following layout::

    base_dir/
        versions/<version>/...
        versions/<version>.staging/...
        CURRENT          # text file with the active version id
        current -> versions/<version>  (best-effort symlink)

The manager does not mutate the application configuration; instead it flips the
``CURRENT`` pointer (and optional ``current`` symlink). Runtime components read
through stable paths such as ``.../current/faiss.index`` and reload when
``ApplicationContext.reload_indices()`` closes their runtime cells.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import contextlib
- from **(absolute)** import json
- from **(absolute)** import shutil
- from **(absolute)** import time
- from **collections.abc** import Iterable, Mapping
- from **dataclasses** import dataclass, field
- from **pathlib** import Path
- from **typing** import Any
- from **codeintel_rev.errors** import RuntimeLifecycleError
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 34)
- class: `LuceneAssets` (line 39)
- function: `link_current_lucene` (line 59)
- class: `IndexAssets` (line 72)
- class: `VersionMeta` (line 115)
- class: `IndexLifecycleManager` (line 140)

## Graph Metrics

- **fan_in**: 5
- **fan_out**: 2
- **cycle_group**: 50

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 4
- recent churn 90: 4

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

IndexAssets, IndexLifecycleManager, LuceneAssets, VersionMeta, link_current_lucene

## Doc Health

- **summary**: Index lifecycle management for FAISS/DuckDB/SCIP artifacts.
- has summary: yes
- param parity: no
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

- score: 2.44

## Side Effects

- filesystem

## Complexity

- branches: 33
- cyclomatic: 34
- loc: 490

## Doc Coverage

- `LuceneAssets` (class): summary=yes, examples=no — Lucene index directories that should flip atomically.
- `link_current_lucene` (function): summary=yes, params=mismatch, examples=no — Copy Lucene assets into a version directory and flip the CURRENT pointer.
- `IndexAssets` (class): summary=yes, examples=no — File-system assets that must advance together for one index version.
- `VersionMeta` (class): summary=yes, examples=no — Metadata recorded for each version directory.
- `IndexLifecycleManager` (class): summary=yes, examples=no — Manage staged/published index versions under a base directory.

## Tags

low-coverage, public-api
