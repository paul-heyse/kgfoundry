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
- from **codeintel_rev.eval.hybrid_evaluator** import EvalConfig, HybridPoolEvaluator
- from **codeintel_rev.indexing.index_lifecycle** import IndexAssets, IndexLifecycleManager
- from **codeintel_rev.io.duckdb_catalog** import DuckDBCatalog
- from **codeintel_rev.io.faiss_manager** import FAISSManager
- from **codeintel_rev.io.xtr_manager** import XTRIndex
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 22)
- variable: `app` (line 23)
- variable: `DEFAULT_XTR_ORACLE` (line 24)
- function: `_get_settings` (line 28)
- variable: `RootOption` (line 39)
- variable: `ExtraOption` (line 40)
- variable: `VersionArg` (line 48)
- variable: `PathArg` (line 49)
- variable: `IndexOption` (line 50)
- variable: `IdMapOption` (line 51)
- variable: `DuckOption` (line 52)
- variable: `OutOption` (line 53)
- function: `global_options` (line 57)
- function: `_default_root` (line 62)
- function: `_resolve_root` (line 69)
- function: `_manager` (line 75)
- function: `_build_assets` (line 80)
- function: `_parse_extras` (line 96)
- function: `_faiss_manager` (line 107)
- function: `_duckdb_catalog` (line 121)
- function: `_load_xtr_index` (line 130)
- function: `_eval_paths` (line 146)
- function: `status_command` (line 153)
- function: `stage_command` (line 163)
- function: `publish_command` (line 179)
- function: `rollback_command` (line 189)
- function: `list_command` (line 199)
- function: `export_idmap_command` (line 211)
- function: `materialize_join_command` (line 233)
- function: `tune_command` (line 245)
- function: `tune_params_command` (line 273)
- function: `_write_tuning_audit` (line 294)
- function: `eval_command` (line 302)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 7
- **cycle_group**: 117

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 5
- recent churn 90: 5

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

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

## Hotspot

- score: 2.32

## Side Effects

- filesystem

## Complexity

- branches: 21
- cyclomatic: 22
- loc: 335

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
- `_load_xtr_index` (function): summary=no, examples=no

## Tags

low-coverage
