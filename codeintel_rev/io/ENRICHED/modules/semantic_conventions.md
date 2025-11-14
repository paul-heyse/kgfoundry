# observability/semantic_conventions.py

## Docstring

```
Shared OpenTelemetry semantic convention helpers for CodeIntel.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json

## Definitions

- class: `Attrs` (line 10)
- function: `as_kv` (line 110)
- function: `to_label_str` (line 128)

## Graph Metrics

- **fan_in**: 20
- **fan_out**: 0
- **cycle_group**: 6

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

Attrs, as_kv, to_label_str

## Doc Health

- **summary**: Shared OpenTelemetry semantic convention helpers for CodeIntel.
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

- score: 2.18

## Side Effects

- none detected

## Complexity

- branches: 2
- cyclomatic: 3
- loc: 151

## Doc Coverage

- `Attrs` (class): summary=yes, examples=no — Trusted attribute keys used across spans, metrics, and logs.
- `as_kv` (function): summary=yes, params=mismatch, examples=no — Return a dict filtered to values that are not ``None``.
- `to_label_str` (function): summary=yes, params=ok, examples=no — Return a deterministic string label for structured values.

## Tags

low-coverage, public-api
