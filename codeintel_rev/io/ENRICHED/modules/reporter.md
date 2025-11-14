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

- function: `_env_retention` (line 48)
- function: `_infer_stop_reason_from_events` (line 57)
- function: `_default_budget_snapshot` (line 71)
- function: `_checkpoint_hit` (line 88)
- function: `_checkpoint_summaries` (line 101)
- function: `_compute_ops_coverage` (line 122)
- function: `_normalize_stage_event` (line 147)
- function: `_build_stage_summary` (line 176)
- function: `_budgets_from_timeline` (line 211)
- class: `RunRecord` (line 236)
- class: `RunReport` (line 278)
- class: `RunReportStore` (line 326)
- variable: `RUN_REPORT_STORE` (line 483)
- function: `start_run` (line 486)
- function: `finalize_run` (line 504)
- function: `record_timeline_payload` (line 522)
- function: `record_step_payload` (line 527)
- function: `emit_checkpoint` (line 532)
- function: `_build_operations` (line 549)
- function: `_collect` (line 588)
- function: `build_report` (line 609)
- function: `build_run_report_v2` (line 691)
- function: `report_to_json` (line 734)
- class: `RunReportStage` (line 785)
- class: `RunReportV2` (line 808)
- function: `render_mermaid` (line 836)
- function: `render_markdown` (line 874)
- function: `render_markdown_v2` (line 951)

## Graph Metrics

- **fan_in**: 6
- **fan_out**: 7
- **cycle_group**: 79

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

RUN_REPORT_STORE, RunReport, RunReportStore, RunReportV2, build_report, build_run_report_v2, emit_checkpoint, finalize_run, record_step_payload, record_timeline_payload, render_markdown, render_markdown_v2, render_mermaid, report_to_json, start_run

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

- score: 3.06

## Side Effects

- filesystem

## Complexity

- branches: 127
- cyclomatic: 128
- loc: 986

## Doc Coverage

- `_env_retention` (function): summary=no, examples=no
- `_infer_stop_reason_from_events` (function): summary=no, examples=no
- `_default_budget_snapshot` (function): summary=no, examples=no
- `_checkpoint_hit` (function): summary=no, examples=no
- `_checkpoint_summaries` (function): summary=no, examples=no
- `_compute_ops_coverage` (function): summary=no, examples=no
- `_normalize_stage_event` (function): summary=yes, params=ok, examples=no — Normalize event kind to a stage label.
- `_build_stage_summary` (function): summary=yes, params=ok, examples=no — Return ordered stage summaries and the last completed stage.
- `_budgets_from_timeline` (function): summary=no, examples=no
- `RunRecord` (class): summary=yes, examples=no — Mutable storage for a sampled run.

## Tags

low-coverage, public-api, reexport-hub
