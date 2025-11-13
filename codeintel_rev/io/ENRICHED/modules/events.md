# telemetry/events.py

## Docstring

```
Typed event helpers shared across telemetry modules.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Mapping
- from **dataclasses** import dataclass, field
- from **typing** import Any

## Definitions

- class: `RunCheckpoint` (line 18)
- class: `TimelineEvent` (line 42)
- function: `checkpoint_event` (line 55)
- function: `coerce_event` (line 91)

## Graph Metrics

- **fan_in**: 2
- **fan_out**: 1
- **cycle_group**: 41

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

RunCheckpoint, TimelineEvent, checkpoint_event, coerce_event

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

- score: 1.64

## Side Effects

- none detected

## Complexity

- branches: 4
- cyclomatic: 5
- loc: 124

## Doc Coverage

- `RunCheckpoint` (class): summary=yes, examples=no — Structured checkpoint emitted after significant pipeline stages.
- `TimelineEvent` (class): summary=yes, examples=no — Normalized representation of a timeline entry.
- `checkpoint_event` (function): summary=yes, params=mismatch, examples=no — Create a RunCheckpoint instance.
- `coerce_event` (function): summary=yes, params=ok, examples=no — Coerce a raw timeline payload into :class:`TimelineEvent`.

## Tags

low-coverage, public-api
