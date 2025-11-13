# risk_hotspots.py

## Docstring

```
Hotspot scoring utilities.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import math
- from **(absolute)** import shutil
- from **(absolute)** import subprocess
- from **functools** import lru_cache
- from **pathlib** import Path
- from **typing** import Any

## Definitions

- function: `compute_hotspot_score` (line 16)
- function: `_git_churn` (line 48)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 1

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 3
- recent churn 90: 3

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Hotspot scoring utilities.
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

- score: 1.71

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 9
- cyclomatic: 10
- loc: 79

## Doc Coverage

- `compute_hotspot_score` (function): summary=yes, params=ok, examples=no — Compute a heuristic hotspot score for a module record.
- `_git_churn` (function): summary=yes, params=ok, examples=no — Return the number of commits touching ``path``.

## Tags

low-coverage
