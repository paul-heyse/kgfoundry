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
- from **codeintel_rev.metrics.registry** import MCP_RUN_ERRORS_TOTAL, MCP_RUNS_TOTAL
- from **codeintel_rev.observability.semantic_conventions** import Attrs
- from **codeintel_rev.telemetry.context** import current_run_id, current_session
- from **codeintel_rev.telemetry.events** import RunCheckpoint, TimelineEvent, checkpoint_event, coerce_event

## Definitions

- function: `_env_retention` (line 49)
- function: `_infer_stop_reason_from_events` (line 58)
- function: `_default_budget_snapshot` (line 72)
- function: `_checkpoint_hit` (line 89)
- function: `_checkpoint_summaries` (line 102)
- function: `_compute_ops_coverage` (line 123)
- function: `_normalize_stage_event` (line 148)
- function: `_build_stage_summary` (line 177)
- function: `_budgets_from_timeline` (line 248)
- class: `RunRecord` (line 273)
- class: `RunReport` (line 315)
- class: `RunReportStore` (line 363)
- variable: `RUN_REPORT_STORE` (line 520)
- function: `start_run` (line 523)
- function: `finalize_run` (line 541)
- function: `record_timeline_payload` (line 559)
- function: `record_step_payload` (line 564)
- function: `emit_checkpoint` (line 569)
- function: `_build_operations` (line 586)
- function: `_collect` (line 625)
- function: `build_report` (line 646)
- function: `build_run_report_v2` (line 728)
- function: `report_to_json` (line 814)
- class: `RunReportStage` (line 865)
- class: `RunReportV2` (line 898)
- function: `render_mermaid` (line 938)
- function: `render_markdown` (line 976)
- function: `render_markdown_v2` (line 1053)

## Graph Metrics

- **fan_in**: 6
- **fan_out**: 8
- **cycle_group**: 44

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 9
- recent churn 90: 9

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

- score: 3.14

## Side Effects

- filesystem

## Complexity

- branches: 152
- cyclomatic: 153
- loc: 1128

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
