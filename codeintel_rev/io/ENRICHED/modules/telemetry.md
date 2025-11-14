# cli/telemetry.py

## Docstring

```
Telemetry-focused CLI commands.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **pathlib** import Path
- from **typing** import Annotated
- from **(absolute)** import typer
- from **codeintel_rev.observability.reporting** import build_timeline_run_report

## Definitions

- variable: `app` (line 13)
- variable: `SessionArg` (line 15)
- variable: `RunIdOption` (line 16)
- variable: `TimelineDirOption` (line 24)
- function: `run_report` (line 35)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 2
- **cycle_group**: 136

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 1
- recent churn 90: 1

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Telemetry-focused CLI commands.
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

- score: 1.19

## Side Effects

- filesystem

## Complexity

- branches: 0
- cyclomatic: 1
- loc: 47

## Doc Coverage

- `run_report` (function): summary=yes, params=mismatch, examples=no — Render a run report from Timeline JSONL artifacts.

## Tags

low-coverage
