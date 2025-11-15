# module_utils.py

## Docstring

```
Helpers for converting between module paths and dotted names.
```

## Imports

- from **__future__** import annotations
- from **pathlib** import Path

## Definitions

- function: `normalize_module_name` (line 9)
- function: `module_name_candidates` (line 34)
- function: `resolve_relative_module` (line 59)
- function: `import_targets_for_entry` (line 87)

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 0
- **cycle_group**: 95

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

- **summary**: Helpers for converting between module paths and dotted names.
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

- score: 2.00

## Side Effects

- filesystem

## Complexity

- branches: 18
- cyclomatic: 19
- loc: 123

## Doc Coverage

- `normalize_module_name` (function): summary=yes, params=ok, examples=no — Return a dotted module name for a repo-relative path.
- `module_name_candidates` (function): summary=yes, params=ok, examples=no — Return candidate module names (with and without prefix).
- `resolve_relative_module` (function): summary=yes, params=ok, examples=no — Resolve a relative import into an absolute dotted module name.
- `import_targets_for_entry` (function): summary=yes, params=ok, examples=no — Return candidate absolute module names for a single import entry.

## Tags

low-coverage
