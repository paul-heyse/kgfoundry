# observability/ledger.py

## Docstring

```
Append-only run ledger utilities.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import io
- from **(absolute)** import json
- from **collections.abc** import Mapping
- from **dataclasses** import dataclass
- from **datetime** import UTC, datetime
- from **pathlib** import Path

## Definitions

- function: `ensure_ledger_root` (line 15)
- function: `dated_run_dir` (line 32)
- class: `RunLedger` (line 53)

## Graph Metrics

- **fan_in**: 4
- **fan_out**: 1
- **cycle_group**: 41

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

RunLedger, dated_run_dir, ensure_ledger_root

## Doc Health

- **summary**: Append-only run ledger utilities.
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

- score: 1.85

## Side Effects

- filesystem

## Complexity

- branches: 5
- cyclomatic: 6
- loc: 114

## Doc Coverage

- `ensure_ledger_root` (function): summary=yes, params=ok, examples=no — Ensure the run-ledger root exists and return it.
- `dated_run_dir` (function): summary=yes, params=ok, examples=no — Return the YYYY-MM-DD ledger directory under ``base_dir``.
- `RunLedger` (class): summary=yes, examples=no — Append-only JSONL ledger scoped to a single run.

## Tags

low-coverage, public-api
