# export_resolver.py

## Docstring

```
Resolve exports and re-exports for module records.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Mapping
- from **typing** import Any
- from **codeintel_rev.module_utils** import import_targets_for_entry, module_name_candidates, normalize_module_name

## Definitions

- variable: `EXPORT_HUB_THRESHOLD` (line 15)
- function: `build_module_name_map` (line 18)
- function: `resolve_exports` (line 44)
- function: `is_reexport_hub` (line 97)
- function: `_public_names` (line 116)

## Dependency Graph

- **fan_in**: 1
- **fan_out**: 2
- **cycle_group**: 17

## Doc Metrics

- **summary**: Resolve exports and re-exports for module records.
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

## Hotspot Score

- score: 2.17

## Side Effects

- none detected

## Complexity

- branches: 33
- cyclomatic: 34
- loc: 134

## Doc Coverage

- `build_module_name_map` (function): summary=yes, params=ok, examples=no — Return mapping of module name → module row for quick lookup.
- `resolve_exports` (function): summary=yes, params=ok, examples=no — Return exports resolved from star-imports and re-export metadata.
- `is_reexport_hub` (function): summary=yes, params=ok, examples=no — Return True when a module behaves like a re-export hub.
- `_public_names` (function): summary=no, examples=no

## Tags

low-coverage
