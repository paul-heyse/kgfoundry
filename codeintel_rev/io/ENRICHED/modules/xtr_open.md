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

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 5
- **cycle_group**: 154

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 2
- recent churn 90: 2

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Fail-fast probe for XTR artifacts.
- has summary: yes
- param parity: yes
- examples present: yes

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Hotspot

- score: 2.03

## Side Effects

- filesystem

## Complexity

- branches: 11
- cyclomatic: 12
- loc: 189

## Doc Coverage

- `xtr_open` (function): summary=yes, params=ok, examples=yes — Validate that XTR artifacts are present and readable.
- `_exit_with_problem` (function): summary=no, examples=no
- `main` (function): summary=yes, params=ok, examples=no — Execute the Typer CLI.

## Tags

low-coverage
