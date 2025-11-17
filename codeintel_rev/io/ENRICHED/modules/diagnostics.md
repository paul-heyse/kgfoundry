# app/routers/diagnostics.py

## Docstring

```
Diagnostics endpoints (disabled - observability removed).
```

## Imports

- from **__future__** import annotations
- from **fastapi** import APIRouter
- from **fastapi.responses** import JSONResponse, PlainTextResponse

## Definitions

- variable: `router` (line 8)
- function: `get_run_report_markdown` (line 15)
- function: `get_run_report` (line 38)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 0
- **cycle_group**: 41

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 8
- recent churn 90: 8

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Diagnostics endpoints (disabled - observability removed).
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

## Config References

- app/hypercorn.toml

## Hotspot

- score: 0.76

## Side Effects

- none detected

## Complexity

- branches: 0
- cyclomatic: 1
- loc: 58

## Doc Coverage

- `get_run_report_markdown` (function): summary=yes, params=ok, examples=no — Diagnostics endpoint disabled - observability removed.
- `get_run_report` (function): summary=yes, params=ok, examples=no — Diagnostics endpoint disabled - observability removed.

## Tags

fastapi, low-coverage
