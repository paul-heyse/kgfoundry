# app/routers/diagnostics.py

## Docstring

```
Diagnostics endpoints for runtime execution ledger reports.
```

## Imports

- from **__future__** import annotations
- from **fastapi** import APIRouter, HTTPException
- from **fastapi.responses** import JSONResponse, PlainTextResponse
- from **codeintel_rev.observability** import execution_ledger

## Definitions

- variable: `router` (line 10)
- function: `get_run_report` (line 14)
- function: `get_run_report_markdown` (line 35)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 1
- **cycle_group**: 60

## Ownership

- bus factor: 0.00
- recent churn 30: 0
- recent churn 90: 0

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Diagnostics endpoints for runtime execution ledger reports.
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

## Config References

- app/hypercorn.toml

## Hotspot

- score: 1.24

## Side Effects

- none detected

## Complexity

- branches: 2
- cyclomatic: 3
- loc: 54

## Doc Coverage

- `get_run_report` (function): summary=yes, params=mismatch, examples=no — Return the execution ledger report for ``run_id`` as JSON.
- `get_run_report_markdown` (function): summary=yes, params=mismatch, examples=no — Return execution ledger report rendered as Markdown.

## Tags

fastapi, low-coverage
