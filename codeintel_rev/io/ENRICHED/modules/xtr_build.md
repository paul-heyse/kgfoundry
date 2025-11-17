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
- from **(absolute)** import numpy

## Definitions

- variable: `np` (line 21)
- class: `XTRBuildSummary` (line 25)
- function: `_iter_chunk_text` (line 36)
- function: `_gather_chunk_vectors` (line 83)
- function: `_write_token_matrix` (line 145)
- function: `build_xtr_index` (line 215)
- function: `main` (line 308)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 6
- **cycle_group**: 90

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 9
- recent churn 90: 9

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Utilities for building and verifying XTR token indexes.
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

- score: 2.26

## Side Effects

- filesystem

## Complexity

- branches: 17
- cyclomatic: 18
- loc: 315

## Doc Coverage

- `XTRBuildSummary` (class): summary=yes, examples=no — Metadata describing a freshly built XTR token index.
- `_iter_chunk_text` (function): summary=yes, params=ok, examples=no — Yield (chunk_id, content) pairs from the DuckDB catalog.
- `_gather_chunk_vectors` (function): summary=yes, params=ok, examples=no — Collect encoded vectors and offsets for all chunks.
- `_write_token_matrix` (function): summary=yes, params=ok, examples=no — Persist buffered token vectors to memmap storage.
- `build_xtr_index` (function): summary=yes, params=ok, examples=no — Build XTR token artifacts from DuckDB chunks.
- `main` (function): summary=yes, params=ok, examples=no — Entry point allowing ``python -m codeintel_rev.indexing.xtr_build``.

## Tags

low-coverage
