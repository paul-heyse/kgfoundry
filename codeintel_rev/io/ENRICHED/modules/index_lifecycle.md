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

- class: `LuceneAssets` (line 39)
- function: `iter_dirs` (line 45)
- function: `link_current_lucene` (line 59)
- class: `IndexAssets` (line 72)
- function: `ensure_exists` (line 82)
- class: `VersionMeta` (line 111)
- function: `to_json` (line 118)
- class: `IndexLifecycleManager` (line 136)
- function: `__init__` (line 139)
- function: `current_version` (line 147)
- function: `current_dir` (line 161)
- function: `list_versions` (line 177)
- function: `read_assets` (line 193)
- function: `prepare` (line 234)
- function: `publish` (line 308)
- function: `rollback` (line 358)
- function: `link_lucene_assets` (line 395)
- function: `_write_current_pointer` (line 435)
- function: `_maybe_dir` (line 445)
- function: `_copy_file` (line 449)
- function: `_copy_tree` (line 454)

## Tags

overlay-needed, public-api
