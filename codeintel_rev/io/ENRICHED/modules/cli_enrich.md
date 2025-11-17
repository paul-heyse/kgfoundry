# cli_enrich.py

## Docstring

```
Compatibility CLI that aggregates pipeline, analytics, and overlay commands.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import typer
- from **(absolute)** import codeintel_rev.cli.enrich_analytics
- from **(absolute)** import codeintel_rev.cli.enrich_overlays
- from **(absolute)** import codeintel_rev.cli.enrich_pipeline
- from **codeintel_rev.cli.enrich_pipeline** import ScanInputs, ScipContext, apply_tagging, build_module_row, outline_nodes_for, type_error_count

## Definitions

- variable: `app` (line 19)
- variable: `normalize_global_cli_args` (line 46)
- function: `main` (line 49)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 3
- **cycle_group**: 93

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 33
- recent churn 90: 33

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

- score: 1.43

## Side Effects

- none detected

## Complexity

- branches: 1
- cyclomatic: 2
- loc: 56

## Doc Coverage

- `main` (function): summary=yes, params=ok, examples=no — Invoke the compatibility CLI app.

## Tags

low-coverage
