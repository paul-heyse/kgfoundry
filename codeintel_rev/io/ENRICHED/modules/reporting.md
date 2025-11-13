# observability/reporting.py

## Docstring

```
Timeline-based run report builder and CLI helpers.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **(absolute)** import os
- from **dataclasses** import dataclass, field
- from **pathlib** import Path
- from **typing** import Any

## Definitions

- class: `TimelineRunReport` (line 13)
- function: `build_timeline_run_report` (line 39)
- function: `_resolve_timeline_dir` (line 96)
- function: `_load_events` (line 104)
- function: `_summarize_events` (line 124)
- function: `_collect_channel_stats` (line 146)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 103

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

- **summary**: Timeline-based run report builder and CLI helpers.
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

- score: 1.90

## Side Effects

- filesystem

## Complexity

- branches: 19
- cyclomatic: 20
- loc: 159

## Doc Coverage

- `TimelineRunReport` (class): summary=yes, examples=no — Structured summary derived from Timeline JSONL records.
- `build_timeline_run_report` (function): summary=yes, params=ok, examples=no — Build a run report by parsing Timeline JSONL artifacts.
- `_resolve_timeline_dir` (function): summary=no, examples=no
- `_load_events` (function): summary=no, examples=no
- `_summarize_events` (function): summary=no, examples=no
- `_collect_channel_stats` (function): summary=no, examples=no

## Tags

low-coverage
