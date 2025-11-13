# bin/eval_coverage.py

## Docstring

```
Command-line entry point for SCIP function coverage evaluation.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import argparse
- from **(absolute)** import json
- from **(absolute)** import sys
- from **pathlib** import Path
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **codeintel_rev.config.settings** import load_settings
- from **codeintel_rev.evaluation.scip_coverage** import SCIPCoverageEvaluator
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 16)
- function: `build_parser` (line 19)
- function: `main` (line 46)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 3
- **cycle_group**: 90

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 2
- recent churn 90: 2

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Command-line entry point for SCIP function coverage evaluation.
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

- filesystem

## Complexity

- branches: 1
- cyclomatic: 2
- loc: 95

## Doc Coverage

- `build_parser` (function): summary=yes, params=ok, examples=no — Return an argument parser for the coverage evaluator CLI.
- `main` (function): summary=yes, params=ok, examples=no — Execute the coverage evaluator with the provided CLI arguments.

## Tags

low-coverage
