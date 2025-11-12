# enrich/ownership.py

## Docstring

```
Ownership, churn, and bus-factor analytics sourced from Git history.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import subprocess
- from **collections** import Counter
- from **collections.abc** import Sequence
- from **dataclasses** import dataclass, field
- from **datetime** import UTC, datetime, timedelta
- from **fnmatch** import fnmatch
- from **pathlib** import Path
- from **git** import Repo

## Definitions

- variable: `GitRepo` (line 17)
- class: `FileOwnership` (line 23)
- class: `OwnershipIndex` (line 34)
- function: `compute_ownership` (line 41)
- function: `_normalize_windows` (line 72)
- function: `_try_open_repo` (line 79)
- function: `_stats_via_gitpython` (line 88)
- function: `_stats_via_subprocess` (line 123)
- function: `_run_git` (line 157)
- function: `_author_name` (line 173)
- function: `_top_k` (line 181)
- function: `_bus_factor` (line 186)
- function: `_codeowners_lookup` (line 193)
- function: `_glob_like_match` (line 215)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 0
- **cycle_group**: 8

## Ownership

- bus factor: 0.00
- recent churn 30: 0
- recent churn 90: 0

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

FileOwnership, OwnershipIndex, compute_ownership

## Doc Health

- **summary**: Ownership, churn, and bus-factor analytics sourced from Git history.
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

## Config References

- enrich/tagging_rules.yaml
- enrich/README.md

## Hotspot

- score: 1.91

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 35
- cyclomatic: 36
- loc: 222

## Doc Coverage

- `FileOwnership` (class): summary=yes, examples=no — Aggregated ownership metadata for a single file.
- `OwnershipIndex` (class): summary=yes, examples=no — Collection of :class:`FileOwnership` entries keyed by relative path.
- `compute_ownership` (function): summary=yes, params=mismatch, examples=no — Return ownership metrics for ``rel_paths`` relative to ``repo_root``.
- `_normalize_windows` (function): summary=no, examples=no
- `_try_open_repo` (function): summary=no, examples=no
- `_stats_via_gitpython` (function): summary=no, examples=no
- `_stats_via_subprocess` (function): summary=no, examples=no
- `_run_git` (function): summary=no, examples=no
- `_author_name` (function): summary=no, examples=no
- `_top_k` (function): summary=no, examples=no

## Tags

low-coverage, public-api
