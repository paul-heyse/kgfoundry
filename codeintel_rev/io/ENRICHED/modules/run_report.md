# observability/run_report.py

## Docstring

```
Utilities for composing run reports from JSONL ledgers.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **collections.abc** import Iterable, Mapping
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import Any

## Definitions

- class: `LedgerRunReport` (line 13)
- function: `load_ledger` (line 23)
- function: `infer_stop_reason` (line 53)
- function: `build_run_report` (line 80)

## Graph Metrics

- **fan_in**: 2
- **fan_out**: 1
- **cycle_group**: 34

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 1
- recent churn 90: 1

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Utilities for composing run reports from JSONL ledgers.
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

- score: 1.87

## Side Effects

- filesystem

## Complexity

- branches: 11
- cyclomatic: 12
- loc: 110

## Doc Coverage

- `LedgerRunReport` (class): summary=yes, examples=no — Structured run report derived from a run ledger.
- `load_ledger` (function): summary=yes, params=ok, examples=no — Return all JSONL records contained in ``path`` (best effort).
- `infer_stop_reason` (function): summary=yes, params=ok, examples=no — Return a human-readable stop reason based on structured step events.
- `build_run_report` (function): summary=yes, params=ok, examples=no — Compose a report for ``run_id`` using the JSONL ledger at ``ledger_path``.

## Tags

low-coverage
