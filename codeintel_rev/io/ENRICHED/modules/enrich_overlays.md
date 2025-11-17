# cli/enrich_overlays.py

## Docstring

```
Overlay-focused CLI for enrichment tooling.
```

## Imports

- from **__future__** import annotations
- from **dataclasses** import replace
- from **pathlib** import Path
- from **(absolute)** import typer
- from **(absolute)** import codeintel_rev.cli.enrich_pipeline
- from **codeintel_rev.enrich.stubs_overlay** import activate_overlays, deactivate_all, generate_overlay_for_file

## Definitions

- variable: `app` (line 17)
- function: `overlays` (line 22)
- function: `main` (line 113)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 2
- **cycle_group**: 83

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

app

## Doc Health

- **summary**: Overlay-focused CLI for enrichment tooling.
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

- score: 1.97

## Side Effects

- filesystem

## Complexity

- branches: 16
- cyclomatic: 17
- loc: 122

## Doc Coverage

- `overlays` (function): summary=no, examples=no
- `main` (function): summary=no, examples=no

## Tags

low-coverage, public-api
