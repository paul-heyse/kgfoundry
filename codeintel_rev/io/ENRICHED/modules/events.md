# telemetry/events.py

## Docstring

```
Typed event helpers shared across telemetry modules.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Mapping, Sequence
- from **dataclasses** import dataclass, field
- from **typing** import Any

## Definitions

- class: `RunCheckpoint` (line 20)
- class: `TimelineEvent` (line 44)
- function: `checkpoint_event` (line 57)
- function: `coerce_event` (line 93)
- class: `RunEventRecord` (line 129)
- function: `normalize_run_event` (line 150)
- function: `_maybe_str` (line 194)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 47

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 4
- recent churn 90: 4

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

RunCheckpoint, RunEventRecord, TimelineEvent, checkpoint_event, coerce_event, normalize_run_event

## Doc Health

- **summary**: Typed event helpers shared across telemetry modules.
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

- score: 1.68

## Side Effects

- none detected

## Complexity

- branches: 8
- cyclomatic: 9
- loc: 198

## Doc Coverage

- `RunCheckpoint` (class): summary=yes, examples=no — Structured checkpoint emitted after significant pipeline stages.
- `TimelineEvent` (class): summary=yes, examples=no — Normalized representation of a timeline entry.
- `checkpoint_event` (function): summary=yes, params=mismatch, examples=no — Create a RunCheckpoint instance.
- `coerce_event` (function): summary=yes, params=ok, examples=no — Coerce a raw timeline payload into :class:`TimelineEvent`.
- `RunEventRecord` (class): summary=yes, examples=no — Structured representation of a run-level event.
- `normalize_run_event` (function): summary=yes, params=ok, examples=no — Return a :class:`RunEventRecord` from ``payload`` with defaults applied.
- `_maybe_str` (function): summary=no, examples=no

## Tags

low-coverage, public-api
