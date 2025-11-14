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
- from **collections.abc** import Callable, Mapping, MutableMapping
- from **dataclasses** import asdict, dataclass
- from **datetime** import UTC, datetime
- from **typing** import Any, Literal, cast
- from **opentelemetry** import trace
- from **codeintel_rev.observability.ledger** import RunLedger
- from **codeintel_rev.observability.runtime_observer** import current_run_ledger
- from **codeintel_rev.observability.semantic_conventions** import Attrs, to_label_str

## Definitions

- variable: `trace` (line 16)
- variable: `LOGGER` (line 22)
- variable: `StepStatus` (line 25)
- class: `StepEvent` (line 31)
- function: `_now_iso` (line 40)
- function: `emit_step` (line 44)
- function: `_record_structured_event` (line 82)

## Graph Metrics

- **fan_in**: 9
- **fan_out**: 4
- **cycle_group**: 76

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 1
- recent churn 90: 1

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

StepEvent, StepStatus, emit_step

## Doc Health

- **summary**: Structured step event helpers.
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

- score: 2.47

## Side Effects

- none detected

## Complexity

- branches: 16
- cyclomatic: 17
- loc: 99

## Doc Coverage

- `StepEvent` (class): summary=yes, examples=no — Immutable representation of a discrete pipeline step.
- `_now_iso` (function): summary=no, examples=no
- `emit_step` (function): summary=yes, params=mismatch, examples=no — Emit a structured step event to the current sinks.
- `_record_structured_event` (function): summary=no, examples=no

## Tags

low-coverage, public-api
