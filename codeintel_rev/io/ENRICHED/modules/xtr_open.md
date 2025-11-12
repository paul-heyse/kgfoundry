# ops/runtime/xtr_open.py

## Docstring

```
Fail-fast probe for XTR artifacts.

Example failure payload::

    {
        "type": "https://kgfoundry.dev/problems/resource-unavailable",
        "title": "XTR artifacts unavailable",
        "status": 503,
        "detail": "Index metadata missing.",
        "runtime": "xtr",
        "instance": "/ops/runtime/xtr-open",
    }
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **pathlib** import Path
- from **typing** import Annotated
- from **(absolute)** import typer
- from **codeintel_rev.app.config_context** import resolve_application_paths
- from **codeintel_rev.config.settings** import load_settings
- from **codeintel_rev.errors** import RuntimeUnavailableError
- from **codeintel_rev.io.xtr_manager** import XTRIndex
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 29)
- variable: `APP` (line 30)
- variable: `PROBLEM_INSTANCE` (line 31)
- function: `xtr_open` (line 53)
- function: `_exit_with_problem` (line 165)
- function: `main` (line 182)

## Dependency Graph

- **fan_in**: 0
- **fan_out**: 5
- **cycle_group**: 95

## Tags

cli
