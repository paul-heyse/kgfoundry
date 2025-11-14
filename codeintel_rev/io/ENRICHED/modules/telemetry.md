# retrieval/telemetry.py

## Docstring

```
Stage-level telemetry helpers used by multi-stage retrieval pipelines.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Iterator
- from **contextlib** import contextmanager
- from **dataclasses** import dataclass, field
- from **time** import perf_counter
- from **codeintel_rev.retrieval.types** import StageDecision
- from **codeintel_rev.telemetry.otel_metrics** import build_counter
- from **kgfoundry_common.logging** import get_logger
- from **kgfoundry_common.observability** import MetricsProvider

## Definitions

- class: `StageTiming` (line 17)
- class: `_TimerRuntime` (line 41)
- class: `_StageTimer` (line 83)
- function: `track_stage` (line 147)
- variable: `LOGGER` (line 193)
- function: `record_stage_metric` (line 201)
- function: `record_stage_decision` (line 226)

## Graph Metrics

- **fan_in**: 2
- **fan_out**: 2
- **cycle_group**: 27

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

StageTiming, record_stage_decision, record_stage_metric, track_stage

## Doc Health

- **summary**: Stage-level telemetry helpers used by multi-stage retrieval pipelines.
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

- score: 1.85

## Side Effects

- none detected

## Complexity

- branches: 7
- cyclomatic: 8
- loc: 247

## Doc Coverage

- `StageTiming` (class): summary=yes, examples=no — Snapshot describing how long a stage took relative to its budget.
- `_TimerRuntime` (class): summary=yes, examples=no — Mutable stopwatch backing the frozen stage timer.
- `_StageTimer` (class): summary=no, examples=no
- `track_stage` (function): summary=yes, params=ok, examples=no — Context manager yielding a timer that can be converted into StageTiming.
- `record_stage_metric` (function): summary=yes, params=mismatch, examples=no — Record the provided ``timing`` in Prometheus metrics.
- `record_stage_decision` (function): summary=yes, params=mismatch, examples=no — Increment the stage decision counter for the given outcome.

## Tags

low-coverage, public-api
