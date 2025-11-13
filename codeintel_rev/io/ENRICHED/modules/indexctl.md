# cli/indexctl.py

## Docstring

```
Typer CLI for managing index lifecycle operations.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **(absolute)** import os
- from **collections.abc** import Callable, Sequence
- from **functools** import lru_cache
- from **pathlib** import Path
- from **typing** import Annotated, Literal, cast
- from **(absolute)** import click
- from **(absolute)** import numpy
- from **(absolute)** import typer
- from **codeintel_rev.config.settings** import Settings, load_settings
- from **codeintel_rev.eval.hybrid_evaluator** import EvalConfig, HybridPoolEvaluator
- from **codeintel_rev.indexing.index_lifecycle** import IndexAssets, IndexLifecycleManager
- from **codeintel_rev.io.duckdb_catalog** import DuckDBCatalog
- from **codeintel_rev.io.faiss_manager** import FAISSManager
- from **codeintel_rev.io.xtr_manager** import XTRIndex
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 24)
- variable: `app` (line 25)
- variable: `DEFAULT_XTR_ORACLE` (line 26)
- function: `_get_settings` (line 30)
- variable: `RootOption` (line 41)
- variable: `ExtraOption` (line 42)
- variable: `VersionArg` (line 50)
- variable: `PathArg` (line 51)
- variable: `IndexOption` (line 52)
- variable: `AssetsArg` (line 53)
- variable: `SidecarOption` (line 61)
- variable: `SweepMode` (line 69)
- variable: `IdMapOption` (line 77)
- variable: `DuckOption` (line 78)
- variable: `OutOption` (line 79)
- variable: `ParamSpaceArg` (line 80)
- variable: `EvalTopKOption` (line 84)
- variable: `EvalKFactorOption` (line 88)
- variable: `EvalNProbeOption` (line 92)
- variable: `EvalXtrOracleOption` (line 96)
- function: `global_options` (line 106)
- function: `_default_root` (line 111)
- function: `_resolve_root` (line 118)
- function: `_manager` (line 124)
- function: `_build_assets` (line 129)
- function: `_parse_extras` (line 147)
- function: `_parse_sidecars` (line 158)
- function: `_parse_tune_overrides` (line 177)
- function: `_faiss_manager` (line 217)
- function: `_duckdb_catalog` (line 231)
- function: `_load_xtr_index` (line 245)
- function: `_eval_paths` (line 261)
- function: `status_command` (line 268)
- function: `stage_command` (line 278)
- function: `publish_command` (line 309)
- function: `rollback_command` (line 319)
- function: `list_command` (line 329)
- function: `export_idmap_command` (line 341)
- function: `materialize_join_command` (line 363)
- function: `tune_command` (line 378)
- function: `tune_params_command` (line 428)
- function: `show_profile_command` (line 450)
- function: `_write_tuning_audit` (line 456)
- function: `_run_autotune` (line 467)
- function: `eval_command` (line 493)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 7
- **cycle_group**: 117

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 7
- recent churn 90: 7

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

- score: 2.55

## Side Effects

- filesystem

## Complexity

- branches: 48
- cyclomatic: 49
- loc: 524

## Doc Coverage

- `_get_settings` (function): summary=yes, params=ok, examples=no — Load settings once and reuse for subsequent commands.
- `global_options` (function): summary=yes, params=mismatch, examples=no — Configure shared CLI options.
- `_default_root` (function): summary=no, examples=no
- `_resolve_root` (function): summary=no, examples=no
- `_manager` (function): summary=no, examples=no
- `_build_assets` (function): summary=no, examples=no
- `_parse_extras` (function): summary=no, examples=no
- `_parse_sidecars` (function): summary=no, examples=no
- `_parse_tune_overrides` (function): summary=no, examples=no
- `_faiss_manager` (function): summary=no, examples=no

## Tags

low-coverage
