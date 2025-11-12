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
- class: `VersionMeta` (line 111)
- class: `IndexLifecycleManager` (line 136)

## Dependency Graph

- **fan_in**: 5
- **fan_out**: 2
- **cycle_group**: 39

## Declared Exports (__all__)

IndexAssets, IndexLifecycleManager, LuceneAssets, VersionMeta, link_current_lucene

## Tags

public-api
