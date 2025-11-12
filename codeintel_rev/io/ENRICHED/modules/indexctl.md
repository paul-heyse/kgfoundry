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
- **cycle_group**: 83

## Tags

cli
