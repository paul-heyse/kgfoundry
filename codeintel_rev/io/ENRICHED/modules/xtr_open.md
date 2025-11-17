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
- from **collections.abc** import Callable
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import Annotated, Protocol
- from **(absolute)** import click
- from **(absolute)** import typer
- from **codeintel_rev.app.config_context** import resolve_application_paths
- from **codeintel_rev.config.settings** import Settings, load_settings
- from **codeintel_rev.errors** import RuntimeUnavailableError
- from **codeintel_rev.io.xtr_manager** import XTRIndex

## Definitions

- variable: `APP` (line 31)
- variable: `PROBLEM_INSTANCE` (line 32)
- class: `XtrOpenContext` (line 54)
- class: `_XtrPaths` (line 80)
- function: `_cli_context` (line 85)
- function: `xtr_open` (line 98)
- function: `_exit_with_problem` (line 210)
- function: `main` (line 227)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 5
- **cycle_group**: 139

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

- score: 2.10

## Side Effects

- filesystem

## Complexity

- branches: 14
- cyclomatic: 15
- loc: 234

## Doc Coverage

- `XtrOpenContext` (class): summary=yes, examples=no — Dependency injection context for the xtr-open CLI.
- `_XtrPaths` (class): summary=no, examples=no
- `_cli_context` (function): summary=no, examples=no
- `xtr_open` (function): summary=yes, params=ok, examples=yes — Validate that XTR artifacts are present and readable.
- `_exit_with_problem` (function): summary=no, examples=no
- `main` (function): summary=yes, params=ok, examples=no — Execute the Typer CLI.

## Tags

low-coverage
