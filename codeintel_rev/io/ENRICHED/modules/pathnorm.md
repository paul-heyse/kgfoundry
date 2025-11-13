# enrich/pathnorm.py

## Docstring

```
Helpers for repo-relative path normalization and stable identifiers.
```

## Imports

- from **__future__** import annotations
- from **hashlib** import blake2s
- from **pathlib** import Path

## Definitions

- function: `detect_repo_root` (line 17)
- function: `to_repo_relative` (line 46)
- function: `module_name_from_path` (line 77)
- function: `stable_id_for_path` (line 127)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 0
- **cycle_group**: 16

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 4
- recent churn 90: 4

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

detect_repo_root, module_name_from_path, stable_id_for_path, to_repo_relative

## Doc Health

- **summary**: Helpers for repo-relative path normalization and stable identifiers.
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

- score: 1.54

## Side Effects

- filesystem

## Complexity

- branches: 9
- cyclomatic: 10
- loc: 151

## Doc Coverage

- `detect_repo_root` (function): summary=yes, params=ok, examples=no — Return the closest ancestor containing a ``.git`` directory.
- `to_repo_relative` (function): summary=yes, params=ok, examples=no — Return a POSIX path for ``path`` relative to ``repo_root``.
- `module_name_from_path` (function): summary=yes, params=ok, examples=no — Derive a dotted module name for ``path`` relative to ``repo_root``.
- `stable_id_for_path` (function): summary=yes, params=ok, examples=no — Return a truncated BLAKE2s digest for ``rel_posix``.

## Tags

low-coverage, public-api
