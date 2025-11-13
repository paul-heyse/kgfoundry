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
- from **typing** import Any
- from **codeintel_rev.app.capabilities** import Capabilities
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.telemetry.context** import current_run_id, current_session
- from **codeintel_rev.telemetry.events** import RunCheckpoint, TimelineEvent, checkpoint_event, coerce_event
- from **codeintel_rev.telemetry.prom** import record_run, record_run_error

## Definitions

- function: `_env_retention` (line 41)
- class: `RunRecord` (line 51)
- class: `RunReport` (line 91)
- class: `RunReportStore` (line 137)
- variable: `RUN_REPORT_STORE` (line 280)
- function: `start_run` (line 283)
- function: `finalize_run` (line 301)
- function: `record_timeline_payload` (line 319)
- function: `emit_checkpoint` (line 324)
- function: `_build_operations` (line 341)
- function: `_collect` (line 380)
- function: `build_report` (line 401)
- function: `report_to_json` (line 481)
- function: `render_markdown` (line 505)

## Graph Metrics

- **fan_in**: 4
- **fan_out**: 6
- **cycle_group**: 71

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 3
- recent churn 90: 3

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

RUN_REPORT_STORE, RunReport, RunReportStore, build_report, emit_checkpoint, finalize_run, record_timeline_payload, render_markdown, report_to_json, start_run

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

- score: 2.76

## Side Effects

- filesystem

## Complexity

- branches: 64
- cyclomatic: 65
- loc: 580

## Doc Coverage

- `_env_retention` (function): summary=no, examples=no
- `RunRecord` (class): summary=yes, examples=no — Mutable storage for a sampled run.
- `RunReport` (class): summary=yes, examples=no — Structured run summary consumable by humans and automation.
- `RunReportStore` (class): summary=yes, examples=no — Thread-safe circular buffer of run data.
- `start_run` (function): summary=yes, params=mismatch, examples=no — Register a run at request ingress.
- `finalize_run` (function): summary=yes, params=mismatch, examples=no — Mark the run as complete/partial/error.
- `record_timeline_payload` (function): summary=yes, params=mismatch, examples=no — Subscribe to timeline events.
- `emit_checkpoint` (function): summary=yes, params=mismatch, examples=no — Capture a stage checkpoint tied to the current request.
- `_build_operations` (function): summary=no, examples=no
- `_collect` (function): summary=no, examples=no

## Tags

low-coverage, public-api, reexport-hub
