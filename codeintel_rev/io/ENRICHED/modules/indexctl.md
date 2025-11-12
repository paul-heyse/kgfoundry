# cli/indexctl.py

## Docstring

```
Typer CLI for managing index lifecycle operations.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **(absolute)** import os
- from **functools** import lru_cache
- from **pathlib** import Path
- from **typing** import Annotated
- from **(absolute)** import click
- from **(absolute)** import typer
- from **codeintel_rev.config.settings** import Settings, load_settings
- from **codeintel_rev.eval.hybrid_evaluator** import HybridPoolEvaluator
- from **codeintel_rev.indexing.index_lifecycle** import IndexAssets, IndexLifecycleManager
- from **codeintel_rev.io.duckdb_catalog** import DuckDBCatalog
- from **codeintel_rev.io.faiss_manager** import FAISSManager
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 21)
- variable: `app` (line 22)
- function: `_get_settings` (line 26)
- variable: `RootOption` (line 37)
- variable: `ExtraOption` (line 38)
- variable: `VersionArg` (line 46)
- variable: `PathArg` (line 47)
- variable: `IndexOption` (line 48)
- variable: `IdMapOption` (line 49)
- variable: `DuckOption` (line 50)
- variable: `OutOption` (line 51)
- function: `global_options` (line 55)
- function: `_default_root` (line 60)
- function: `_resolve_root` (line 67)
- function: `_manager` (line 73)
- function: `_build_assets` (line 78)
- function: `_parse_extras` (line 94)
- function: `_faiss_manager` (line 105)
- function: `_duckdb_catalog` (line 119)
- function: `status_command` (line 127)
- function: `stage_command` (line 137)
- function: `publish_command` (line 153)
- function: `rollback_command` (line 163)
- function: `list_command` (line 173)
- function: `export_idmap_command` (line 185)
- function: `materialize_join_command` (line 206)
- function: `tune_command` (line 217)
- function: `eval_hybrid_command` (line 247)

## Dependency Graph

- **fan_in**: 0
- **fan_out**: 6
- **cycle_group**: 113

## Doc Metrics

- **summary**: Typer CLI for managing index lifecycle operations.
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

## Hotspot Score

- score: 2.19

## Side Effects

- filesystem

## Complexity

- branches: 16
- cyclomatic: 17
- loc: 271

## Doc Coverage

- `_get_settings` (function): summary=yes, params=ok, examples=no — Load settings once and reuse for subsequent commands.
- `global_options` (function): summary=yes, params=mismatch, examples=no — Configure shared CLI options.
- `_default_root` (function): summary=no, examples=no
- `_resolve_root` (function): summary=no, examples=no
- `_manager` (function): summary=no, examples=no
- `_build_assets` (function): summary=no, examples=no
- `_parse_extras` (function): summary=no, examples=no
- `_faiss_manager` (function): summary=no, examples=no
- `_duckdb_catalog` (function): summary=no, examples=no
- `status_command` (function): summary=yes, params=ok, examples=no — Print the active version and available versions.

## Tags

low-coverage
