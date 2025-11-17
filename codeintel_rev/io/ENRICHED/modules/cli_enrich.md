# cli_enrich.py

## Docstring

```
Compatibility CLI that aggregates pipeline, analytics, and overlay commands.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import typer
- from **codeintel_rev.cli** import enrich_analytics, enrich_overlays, enrich_pipeline

## Definitions

- variable: `app` (line 9)
- variable: `ScanInputs` (line 36)
- variable: `ScipContext` (line 37)
- variable: `normalize_global_cli_args` (line 42)
- function: `main` (line 45)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 1
- **cycle_group**: 95

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 34
- recent churn 90: 34

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Compatibility CLI that aggregates pipeline, analytics, and overlay commands.
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

- score: 1.15

## Side Effects

- none detected

## Complexity

- branches: 1
- cyclomatic: 2
- loc: 52

## Doc Coverage

- `main` (function): summary=yes, params=ok, examples=no — Invoke the compatibility CLI app.

## Tags

low-coverage
