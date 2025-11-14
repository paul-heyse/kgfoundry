# diagnostics/report_cli.py

## Docstring

```
Diagnostics CLI for rendering run reports from session event ledgers.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **(absolute)** import sys
- from **collections.abc** import Mapping, Sequence
- from **dataclasses** import asdict
- from **enum** import StrEnum
- from **pathlib** import Path
- from **typing** import Annotated, Any
- from **(absolute)** import typer
- from **codeintel_rev.observability.run_report** import LedgerRunReport, infer_stop_reason, load_ledger

## Definitions

- variable: `app` (line 19)
- class: `ReportFormat` (line 22)
- variable: `EventRecord` (line 29)
- function: `_coerce_str` (line 32)
- function: `_coerce_number` (line 38)
- function: `_event_ts` (line 44)
- function: `_event_attrs` (line 51)
- function: `_stage_label` (line 58)
- function: `_group_events_by_run` (line 62)
- function: `_max_ts` (line 77)
- function: `_select_run` (line 88)
- function: `_stage_rows` (line 104)
- function: `_skip_rows` (line 120)
- function: `_render_stage_section` (line 136)
- function: `_render_skip_section` (line 151)
- function: `_render_markdown` (line 166)
- function: `_structured_report` (line 180)
- function: `session_report` (line 199)
- function: `ledger_report` (line 281)
- function: `main` (line 316)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 2
- **cycle_group**: 114

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 7
- recent churn 90: 7

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

app, main

## Doc Health

- **summary**: Diagnostics CLI for rendering run reports from session event ledgers.
- has summary: yes
- param parity: yes
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

- score: 2.13

## Side Effects

- filesystem

## Complexity

- branches: 43
- cyclomatic: 44
- loc: 349

## Doc Coverage

- `ReportFormat` (class): summary=yes, examples=no — Supported output encodings for diagnostics reports.
- `_coerce_str` (function): summary=no, examples=no
- `_coerce_number` (function): summary=no, examples=no
- `_event_ts` (function): summary=no, examples=no
- `_event_attrs` (function): summary=no, examples=no
- `_stage_label` (function): summary=no, examples=no
- `_group_events_by_run` (function): summary=no, examples=no
- `_max_ts` (function): summary=no, examples=no
- `_select_run` (function): summary=no, examples=no
- `_stage_rows` (function): summary=no, examples=no

## Tags

low-coverage, public-api
