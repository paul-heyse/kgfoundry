# cst_build/cst_cli.py

## Docstring

```
CLI entrypoint for CST dataset builds.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Sequence
- from **dataclasses** import dataclass
- from **fnmatch** import fnmatch
- from **pathlib** import Path
- from **(absolute)** import click
- from **codeintel_rev.cst_build.cst_collect** import CSTCollector
- from **codeintel_rev.cst_build.cst_resolve** import StitchCounters, load_modules, load_scip_index, stitch_nodes
- from **codeintel_rev.cst_build.cst_schema** import CollectorStats
- from **codeintel_rev.cst_build.cst_serialize** import DatasetWriter, write_index, write_join_examples

## Definitions

- class: `CLIOptions` (line 25)
- variable: `ROOT_DEFAULT` (line 39)
- variable: `SCIP_DEFAULT` (line 40)
- variable: `MODULES_DEFAULT` (line 41)
- variable: `OUT_DEFAULT` (line 42)
- function: `_build_options` (line 45)
- function: `main` (line 135)
- function: `_iter_py_files` (line 224)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 4
- **cycle_group**: 114

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 4
- recent churn 90: 4

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: CLI entrypoint for CST dataset builds.
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

- score: 2.16

## Side Effects

- filesystem

## Complexity

- branches: 23
- cyclomatic: 24
- loc: 264

## Doc Coverage

- `CLIOptions` (class): summary=yes, examples=no — Normalized command-line options.
- `_build_options` (function): summary=yes, params=ok, examples=no — Extract and normalize CLI options from Click context.
- `main` (function): summary=yes, params=mismatch, examples=no — Entry point invoked by the console script.
- `_iter_py_files` (function): summary=yes, params=ok, examples=no — Discover Python files matching include/exclude glob patterns.

## Tags

low-coverage
