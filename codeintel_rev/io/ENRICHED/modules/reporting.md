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
- from **itertools** import pairwise
- from **pathlib** import Path
- from **typing** import Any
- from **codeintel_rev.observability.timeline** import Timeline

## Definitions

- class: `TimelineRunReport` (line 22)
- function: `render_timeline_markdown` (line 48)
- function: `timeline_mermaid` (line 77)
- function: `_ensure_runs_dir` (line 112)
- function: `render_run_report` (line 118)
- function: `latest_run_report` (line 188)
- function: `build_timeline_run_report` (line 202)
- function: `_resolve_timeline_dir` (line 259)
- function: `resolve_timeline_dir` (line 267)
- function: `_load_events` (line 285)
- function: `_summarize_events` (line 305)
- function: `_collect_channel_stats` (line 327)
- function: `_render_markdown_report` (line 342)

## Graph Metrics

- **fan_in**: 5
- **fan_out**: 2
- **cycle_group**: 46

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 4
- recent churn 90: 4

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

- score: 2.51

## Side Effects

- filesystem

## Complexity

- branches: 41
- cyclomatic: 42
- loc: 384

## Doc Coverage

- `TimelineRunReport` (class): summary=yes, examples=no — Structured summary derived from Timeline JSONL records.
- `render_timeline_markdown` (function): summary=yes, params=ok, examples=no — Return Markdown for the provided :class:`TimelineRunReport`.
- `timeline_mermaid` (function): summary=yes, params=ok, examples=no — Return a Mermaid diagram that visualizes the recorded events.
- `_ensure_runs_dir` (function): summary=no, examples=no
- `render_run_report` (function): summary=yes, params=ok, examples=no — Render Markdown + JSON artifacts for the provided timeline.
- `latest_run_report` (function): summary=yes, params=ok, examples=no — Return metadata for the most recently rendered run report.
- `build_timeline_run_report` (function): summary=yes, params=ok, examples=no — Build a run report by parsing Timeline JSONL artifacts.
- `_resolve_timeline_dir` (function): summary=no, examples=no
- `resolve_timeline_dir` (function): summary=yes, params=ok, examples=no — Return the normalized diagnostics directory used for timeline artifacts.
- `_load_events` (function): summary=no, examples=no

## Tags

low-coverage
