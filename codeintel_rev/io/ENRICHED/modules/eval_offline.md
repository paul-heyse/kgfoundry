# bin/eval_offline.py

## Docstring

```
Command-line entry point for offline FAISS recall evaluation.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import argparse
- from **(absolute)** import json
- from **(absolute)** import sys
- from **pathlib** import Path
- from **codeintel_rev.app.config_context** import ApplicationContext
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 14)
- function: `build_parser` (line 17)
- function: `main` (line 41)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 1
- **cycle_group**: 95

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

- **summary**: Command-line entry point for offline FAISS recall evaluation.
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

- score: 1.24

## Side Effects

- filesystem

## Complexity

- branches: 2
- cyclomatic: 3
- loc: 85

## Doc Coverage

- `build_parser` (function): summary=yes, params=ok, examples=no — Return an argument parser for the offline evaluator CLI.
- `main` (function): summary=yes, params=ok, examples=no — Execute the evaluator using CLI arguments.

## Tags

low-coverage
