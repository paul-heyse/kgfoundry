# risk_hotspots.py

## Docstring

```
Hotspot scoring utilities.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import math
- from **functools** import lru_cache
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING, Any
- from **kgfoundry_common.logging** import get_logger
- from **git** import Repo
- from **git.exc** import GitError
- from **git** import Repo

## Definitions

- variable: `LOGGER` (line 13)
- variable: `GitError` (line 20)
- variable: `GitRepoType` (line 25)
- function: `compute_hotspot_score` (line 28)
- function: `_git_churn` (line 60)
- function: `_open_repo` (line 82)
- function: `_repo_root` (line 101)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 1

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

- score: 1.80

## Side Effects

- filesystem

## Complexity

- branches: 13
- cyclomatic: 14
- loc: 110

## Doc Coverage

- `compute_hotspot_score` (function): summary=yes, params=ok, examples=no — Compute a heuristic hotspot score for a module record.
- `_git_churn` (function): summary=yes, params=mismatch, examples=no — Return the number of commits touching ``path``.
- `_open_repo` (function): summary=yes, params=ok, examples=no — Open project Git repository for analytics.
- `_repo_root` (function): summary=yes, params=ok, examples=no — Return repository root path.

## Tags

low-coverage
