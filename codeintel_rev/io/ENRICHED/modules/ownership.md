# enrich/ownership.py

## Docstring

```
Ownership, churn, and bus-factor analytics sourced from Git history.
```

## Imports

- from **__future__** import annotations
- from **collections** import Counter
- from **collections.abc** import Sequence
- from **dataclasses** import dataclass, field
- from **datetime** import UTC, datetime, timedelta
- from **fnmatch** import fnmatch
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING
- from **kgfoundry_common.logging** import get_logger
- from **git** import Repo
- from **git** import exc
- from **git** import Repo

## Definitions

- variable: `git_exc` (line 21)
- class: `GitRepo` (line 27)
- variable: `GitError` (line 31)
- variable: `LOGGER` (line 32)
- class: `FileOwnership` (line 38)
- class: `OwnershipIndex` (line 49)
- function: `compute_ownership` (line 56)
- function: `_normalize_windows` (line 116)
- function: `_try_open_repo` (line 123)
- function: `_stats_via_gitpython` (line 132)
- function: `_author_name` (line 171)
- function: `_top_k` (line 179)
- function: `_bus_factor` (line 184)
- function: `_codeowners_lookup` (line 191)
- function: `_glob_like_match` (line 211)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 90

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 6
- recent churn 90: 6

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

FileOwnership, OwnershipIndex, compute_ownership

## Doc Health

- **summary**: Ownership, churn, and bus-factor analytics sourced from Git history.
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

## Config References

- enrich/tagging_rules.yaml
- enrich/PLAYBOOK.md
- enrich/README.md

## Hotspot

- score: 2.04

## Side Effects

- filesystem

## Complexity

- branches: 31
- cyclomatic: 32
- loc: 218

## Doc Coverage

- `GitRepo` (class): summary=yes, examples=no — Runtime placeholder for optional GitPython dependency.
- `FileOwnership` (class): summary=yes, examples=no — Aggregated ownership metadata for a single file.
- `OwnershipIndex` (class): summary=yes, examples=no — Collection of :class:`FileOwnership` entries keyed by relative path.
- `compute_ownership` (function): summary=yes, params=ok, examples=no — Return ownership metrics for ``rel_paths`` relative to ``repo_root``.
- `_normalize_windows` (function): summary=no, examples=no
- `_try_open_repo` (function): summary=no, examples=no
- `_stats_via_gitpython` (function): summary=no, examples=no
- `_author_name` (function): summary=no, examples=no
- `_top_k` (function): summary=no, examples=no
- `_bus_factor` (function): summary=no, examples=no

## Tags

low-coverage, public-api
