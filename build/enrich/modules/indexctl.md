# cli/indexctl.py

## Docstring

```
Typer CLI for managing index lifecycle operations.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import os
- from **pathlib** import Path
- from **typing** import Annotated
- from **(absolute)** import click
- from **(absolute)** import typer
- from **codeintel_rev.indexing.index_lifecycle** import IndexAssets, IndexLifecycleManager
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 15)
- variable: `app` (line 16)
- variable: `RootOption` (line 18)
- variable: `ExtraOption` (line 19)
- variable: `VersionArg` (line 27)
- variable: `PathArg` (line 28)
- function: `global_options` (line 32)
- function: `_default_root` (line 37)
- function: `_resolve_root` (line 44)
- function: `_manager` (line 50)
- function: `_build_assets` (line 55)
- function: `_parse_extras` (line 71)
- function: `status_command` (line 83)
- function: `stage_command` (line 93)
- function: `publish_command` (line 109)
- function: `rollback_command` (line 119)
- function: `list_command` (line 129)

## Dependency Graph

- **fan_in**: 0
- **fan_out**: 2
- **cycle_group**: 104

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

- score: 1.73

## Side Effects

- filesystem

## Complexity

- branches: 10
- cyclomatic: 11
- loc: 138

## Doc Coverage

- `global_options` (function): summary=yes, params=mismatch, examples=no — Configure shared CLI options.
- `_default_root` (function): summary=no, examples=no
- `_resolve_root` (function): summary=no, examples=no
- `_manager` (function): summary=no, examples=no
- `_build_assets` (function): summary=no, examples=no
- `_parse_extras` (function): summary=no, examples=no
- `status_command` (function): summary=yes, params=ok, examples=no — Print the active version and available versions.
- `stage_command` (function): summary=yes, params=mismatch, examples=no — Stage a new version by copying assets into the lifecycle root.
- `publish_command` (function): summary=yes, params=mismatch, examples=no — Publish a previously staged version.
- `rollback_command` (function): summary=yes, params=mismatch, examples=no — Rollback to a previously published version.

## Tags

low-coverage
