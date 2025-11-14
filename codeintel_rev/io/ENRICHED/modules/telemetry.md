# cli/telemetry.py

## Docstring

```
Telemetry-focused CLI commands.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **enum** import Enum
- from **pathlib** import Path
- from **typing** import Annotated
- from **(absolute)** import typer
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.observability.reporting** import build_timeline_run_report, render_timeline_markdown, timeline_mermaid
- from **codeintel_rev.observability.runpack** import make_runpack

## Definitions

- variable: `app` (line 20)
- variable: `SessionArg` (line 22)
- variable: `RunIdOption` (line 23)
- variable: `TimelineDirOption` (line 31)
- class: `OutputFormat` (line 41)
- function: `run_report` (line 50)
- function: `runpack` (line 80)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 4
- **cycle_group**: 138

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

- score: 1.67

## Side Effects

- filesystem

## Complexity

- branches: 3
- cyclomatic: 4
- loc: 129

## Doc Coverage

- `OutputFormat` (class): summary=yes, examples=no — Output formats supported by the run report command.
- `run_report` (function): summary=yes, params=mismatch, examples=no — Render a run report from Timeline JSONL artifacts.
- `runpack` (function): summary=yes, params=ok, examples=no — Create a runpack zip for the specified session/run.

## Tags

low-coverage
