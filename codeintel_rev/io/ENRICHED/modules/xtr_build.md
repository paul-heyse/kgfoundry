# indexing/xtr_build.py

## Docstring

```
Utilities for building and verifying XTR token indexes.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **collections.abc** import Iterable, Sequence
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING, Any, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.app.config_context** import resolve_application_paths
- from **codeintel_rev.config.settings** import Settings, load_settings
- from **codeintel_rev.io.duckdb_catalog** import DuckDBCatalog
- from **codeintel_rev.io.xtr_manager** import XTRIndex
- from **codeintel_rev.typing** import NDArrayAny
- from **kgfoundry_common.logging** import get_logger
- from **(absolute)** import numpy

## Definitions

- variable: `np` (line 22)
- variable: `LOGGER` (line 24)
- class: `XTRBuildSummary` (line 28)
- function: `_iter_chunk_text` (line 39)
- function: `_gather_chunk_vectors` (line 86)
- function: `_write_token_matrix` (line 157)
- function: `build_xtr_index` (line 227)
- function: `main` (line 333)

## Dependency Graph

- **fan_in**: 1
- **fan_out**: 6
- **cycle_group**: 60
