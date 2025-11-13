# observability/reporting.py

## Docstring

```
Timeline-based run report builder and CLI helpers.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **(absolute)** import os
- from **collections.abc** import Mapping
- from **dataclasses** import dataclass, field
- from **datetime** import UTC, datetime
- from **pathlib** import Path
- from **typing** import Any
- from **codeintel_rev.observability.timeline** import Timeline

## Definitions

- class: `TimelineRunReport` (line 21)
- function: `_ensure_runs_dir` (line 47)
- function: `render_run_report` (line 53)
- function: `latest_run_report` (line 123)
- function: `build_timeline_run_report` (line 137)
- function: `_resolve_timeline_dir` (line 194)
- function: `_load_events` (line 202)
- function: `_summarize_events` (line 222)
- function: `_collect_channel_stats` (line 244)
- function: `_render_markdown_report` (line 259)

## Graph Metrics

- **fan_in**: 4
- **fan_out**: 2
- **cycle_group**: 77

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

- score: 2.38

## Side Effects

- filesystem

## Complexity

- branches: 32
- cyclomatic: 33
- loc: 301

## Doc Coverage

- `TimelineRunReport` (class): summary=yes, examples=no — Structured summary derived from Timeline JSONL records.
- `_ensure_runs_dir` (function): summary=no, examples=no
- `render_run_report` (function): summary=yes, params=ok, examples=no — Render Markdown + JSON artifacts for the provided timeline.
- `latest_run_report` (function): summary=yes, params=ok, examples=no — Return metadata for the most recently rendered run report.
- `build_timeline_run_report` (function): summary=yes, params=ok, examples=no — Build a run report by parsing Timeline JSONL artifacts.
- `_resolve_timeline_dir` (function): summary=no, examples=no
- `_load_events` (function): summary=no, examples=no
- `_summarize_events` (function): summary=no, examples=no
- `_collect_channel_stats` (function): summary=no, examples=no
- `_render_markdown_report` (function): summary=no, examples=no

## Tags

low-coverage
