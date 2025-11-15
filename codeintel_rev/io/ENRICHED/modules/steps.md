# telemetry/steps.py

## Docstring

```
Structured step event helpers.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import importlib
- from **(absolute)** import json
- from **(absolute)** import logging
- from **collections.abc** import Callable, Mapping
- from **dataclasses** import asdict, dataclass
- from **datetime** import UTC, datetime
- from **typing** import Any, Literal, cast
- from **codeintel_rev.observability.execution_ledger** import record
- from **codeintel_rev.observability.ledger** import RunLedger
- from **codeintel_rev.observability.runtime_observer** import current_run_ledger
- from **codeintel_rev.observability.semantic_conventions** import Attrs, to_label_str
- from **codeintel_rev.telemetry.context** import current_run_id, current_session, current_stage
- from **codeintel_rev.telemetry.otel_shim** import SpanProtocol, trace_api

## Definitions

- variable: `LOGGER` (line 20)
- variable: `StepStatus` (line 23)
- class: `StepEvent` (line 29)
- function: `_now_iso` (line 38)
- function: `emit_step` (line 42)
- function: `_record_structured_event` (line 70)
- function: `_build_step_attrs` (line 89)
- function: `_current_recording_span` (line 101)
- function: `_build_structured_record` (line 106)
- function: `_mirror_step_into_ledger` (line 124)
- function: `_log_step` (line 143)

## Graph Metrics

- **fan_in**: 9
- **fan_out**: 7
- **cycle_group**: 42

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

StepEvent, StepStatus, emit_step

## Doc Health

- **summary**: Structured step event helpers.
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

- score: 2.55

## Side Effects

- none detected

## Complexity

- branches: 16
- cyclomatic: 17
- loc: 148

## Doc Coverage

- `StepEvent` (class): summary=yes, examples=no — Immutable representation of a discrete pipeline step.
- `_now_iso` (function): summary=no, examples=no
- `emit_step` (function): summary=yes, params=ok, examples=no — Emit a structured step event to the current sinks.
- `_record_structured_event` (function): summary=no, examples=no
- `_build_step_attrs` (function): summary=no, examples=no
- `_current_recording_span` (function): summary=no, examples=no
- `_build_structured_record` (function): summary=no, examples=no
- `_mirror_step_into_ledger` (function): summary=no, examples=no
- `_log_step` (function): summary=no, examples=no

## Tags

low-coverage, public-api
