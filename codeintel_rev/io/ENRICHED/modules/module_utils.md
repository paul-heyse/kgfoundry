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
- function: `module_name_candidates` (line 29)
- function: `resolve_relative_module` (line 47)
- function: `import_targets_for_entry` (line 66)

## Dependency Graph

- **fan_in**: 2
- **fan_out**: 0
- **cycle_group**: 1

## Doc Metrics

- **summary**: Helpers for converting between module paths and dotted names.
- has summary: yes
- param parity: no
- examples present: no

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Side Effects

- filesystem

## Complexity

- branches: 18
- cyclomatic: 19
- loc: 89

## Doc Coverage

- `normalize_module_name` (function): summary=yes, params=mismatch, examples=no — Return a dotted module name for a repo-relative path.
- `module_name_candidates` (function): summary=yes, params=mismatch, examples=no — Return candidate module names (with and without prefix).
- `resolve_relative_module` (function): summary=yes, params=mismatch, examples=no — Resolve a relative import into an absolute dotted module name.
- `import_targets_for_entry` (function): summary=yes, params=mismatch, examples=no — Return candidate absolute module names for a single import entry.
