# io/path_utils.py

## Docstring

```
Path safety utilities for repository-scoped operations.
```

## Imports

- from **__future__** import annotations
- from **pathlib** import Path

## Definitions

- class: `PathOutsideRepositoryError` (line 8)
- function: `resolve_within_repo` (line 12)

## Graph Metrics

- **fan_in**: 5
- **fan_out**: 0
- **cycle_group**: 76

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

- **summary**: Path safety utilities for repository-scoped operations.
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

- branches: 4
- cyclomatic: 5
- loc: 55

## Doc Coverage

- `PathOutsideRepositoryError` (class): summary=yes, examples=no — Raised when a path escapes the configured repository root.
- `resolve_within_repo` (function): summary=yes, params=ok, examples=no — Resolve ``target`` against ``repo_root`` and ensure it stays within bounds.

## Tags

low-coverage
