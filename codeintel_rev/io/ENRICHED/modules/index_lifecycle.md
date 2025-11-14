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
- from **(absolute)** import hashlib
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

- variable: `LOGGER` (line 35)
- variable: `MANIFEST_FILE` (line 37)
- variable: `IDMAP_FILE` (line 38)
- variable: `PROFILE_FILE` (line 39)
- class: `LuceneAssets` (line 43)
- function: `link_current_lucene` (line 63)
- class: `IndexAssets` (line 76)
- function: `_file_checksum` (line 118)
- function: `_read_json` (line 128)
- function: `collect_asset_attrs` (line 135)
- function: `_attrs_from_meta` (line 169)
- function: `_attrs_from_idmap` (line 192)
- function: `_attrs_from_tuning` (line 198)
- class: `VersionMeta` (line 219)
- class: `IndexLifecycleManager` (line 244)

## Graph Metrics

- **fan_in**: 5
- **fan_out**: 2
- **cycle_group**: 74

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 8
- recent churn 90: 8

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

IndexAssets, IndexLifecycleManager, LuceneAssets, VersionMeta, collect_asset_attrs, link_current_lucene

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

- score: 2.64

## Side Effects

- filesystem

## Complexity

- branches: 65
- cyclomatic: 66
- loc: 689

## Doc Coverage

- `LuceneAssets` (class): summary=yes, examples=no — Lucene index directories that should flip atomically.
- `link_current_lucene` (function): summary=yes, params=mismatch, examples=no — Copy Lucene assets into a version directory and flip the CURRENT pointer.
- `IndexAssets` (class): summary=yes, examples=no — File-system assets that must advance together for one index version.
- `_file_checksum` (function): summary=no, examples=no
- `_read_json` (function): summary=no, examples=no
- `collect_asset_attrs` (function): summary=yes, params=ok, examples=no — Return manifest attributes derived from staged asset sidecars.
- `_attrs_from_meta` (function): summary=no, examples=no
- `_attrs_from_idmap` (function): summary=no, examples=no
- `_attrs_from_tuning` (function): summary=no, examples=no
- `VersionMeta` (class): summary=yes, examples=no — Metadata recorded for each version directory.

## Tags

low-coverage, public-api
