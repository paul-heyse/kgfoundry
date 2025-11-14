# telemetry/reporter.py

## Docstring

```
In-memory run report builder fed by timeline events.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **(absolute)** import os
- from **(absolute)** import threading
- from **collections** import deque
- from **collections.abc** import Iterable, Mapping, Sequence
- from **dataclasses** import dataclass, field
- from **itertools** import pairwise
- from **typing** import Any
- from **codeintel_rev.app.capabilities** import Capabilities
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.diagnostics.detectors** import detect
- from **codeintel_rev.telemetry.context** import current_run_id, current_session
- from **codeintel_rev.telemetry.events** import RunCheckpoint, TimelineEvent, checkpoint_event, coerce_event
- from **codeintel_rev.telemetry.prom** import record_run, record_run_error

## Definitions

- function: `_env_retention` (line 45)
- function: `_infer_stop_reason_from_events` (line 54)
- function: `_default_budget_snapshot` (line 68)
- function: `_checkpoint_hit` (line 85)
- function: `_checkpoint_summaries` (line 98)
- function: `_compute_ops_coverage` (line 119)
- function: `_budgets_from_timeline` (line 136)
- class: `RunRecord` (line 161)
- class: `RunReport` (line 203)
- class: `RunReportStore` (line 251)
- variable: `RUN_REPORT_STORE` (line 408)
- function: `start_run` (line 411)
- function: `finalize_run` (line 429)
- function: `record_timeline_payload` (line 447)
- function: `record_step_payload` (line 452)
- function: `emit_checkpoint` (line 457)
- function: `_build_operations` (line 474)
- function: `_collect` (line 513)
- function: `build_report` (line 534)
- function: `report_to_json` (line 616)
- function: `render_mermaid` (line 666)
- function: `render_markdown` (line 704)

## Graph Metrics

- **fan_in**: 6
- **fan_out**: 7
- **cycle_group**: 79

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 6
- recent churn 90: 6

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

RUN_REPORT_STORE, RunReport, RunReportStore, build_report, emit_checkpoint, finalize_run, record_step_payload, record_timeline_payload, render_markdown, render_mermaid, report_to_json, start_run

## Doc Health

- **summary**: In-memory run report builder fed by timeline events.
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

- score: 3.01

## Side Effects

- filesystem

## Complexity

- branches: 107
- cyclomatic: 108
- loc: 779

## Doc Coverage

- `_env_retention` (function): summary=no, examples=no
- `_infer_stop_reason_from_events` (function): summary=no, examples=no
- `_default_budget_snapshot` (function): summary=no, examples=no
- `_checkpoint_hit` (function): summary=no, examples=no
- `_checkpoint_summaries` (function): summary=no, examples=no
- `_compute_ops_coverage` (function): summary=no, examples=no
- `_budgets_from_timeline` (function): summary=no, examples=no
- `RunRecord` (class): summary=yes, examples=no — Mutable storage for a sampled run.
- `RunReport` (class): summary=yes, examples=no — Structured run summary consumable by humans and automation.
- `RunReportStore` (class): summary=yes, examples=no — Thread-safe circular buffer of run data.

## Tags

low-coverage, public-api, reexport-hub
