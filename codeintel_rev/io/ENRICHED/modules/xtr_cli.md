# mcp_server/retrieval/xtr_cli.py

## Docstring

```
Typer CLI for building, verifying, and probing XTR artifacts.
```

## Imports

- from **__future__** import annotations
- from **typing** import Annotated
- from **(absolute)** import typer
- from **codeintel_rev.app.config_context** import resolve_application_paths
- from **codeintel_rev.config.settings** import load_settings
- from **codeintel_rev.indexing.xtr_build** import build_xtr_index
- from **codeintel_rev.io.xtr_manager** import XTRIndex

## Definitions

- variable: `app` (line 14)
- function: `build` (line 31)
- function: `verify` (line 44)
- function: `search` (line 70)
- function: `main` (line 158)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 5
- **cycle_group**: 116

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 5
- recent churn 90: 5

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Typer CLI for building, verifying, and probing XTR artifacts.
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

- score: 2.12

## Side Effects

- filesystem

## Complexity

- branches: 12
- cyclomatic: 13
- loc: 165

## Doc Coverage

- `build` (function): summary=yes, params=ok, examples=no — Build token-level XTR artifacts from the DuckDB catalog.
- `verify` (function): summary=yes, params=ok, examples=no — Verify that XTR artifacts can be opened.
- `search` (function): summary=yes, params=ok, examples=no — Run a quick XTR search (wide or narrow depending on candidate ids).
- `main` (function): summary=yes, params=ok, examples=no — Execute the Typer app.

## Tags

low-coverage
