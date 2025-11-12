# enrich/stubs_overlay.py

## Docstring

```
Targeted overlay generation with opt-in activation.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import platform
- from **collections.abc** import Mapping, MutableMapping, Sequence
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **codeintel_rev.enrich.libcst_bridge** import DefEntry, ImportEntry, ModuleIndex, index_module
- from **codeintel_rev.enrich.output_writers** import write_json
- from **codeintel_rev.enrich.scip_reader** import SCIPIndex

## Definitions

- class: `OverlayPolicy` (line 17)
- class: `OverlayResult` (line 31)
- function: `generate_overlay_for_file` (line 41)
- function: `activate_overlays` (line 158)
- function: `deactivate_all` (line 207)
- function: `_overlay_path` (line 245)
- function: `_normalized_module_key` (line 269)
- function: `_module_name_from_path` (line 289)
- function: `_collect_star_reexports` (line 313)
- function: `_extract_simple_name` (line 344)
- function: `_build_overlay_text` (line 372)
- function: `_render_star_exports` (line 436)
- function: `_render_public_defs` (line 461)
- function: `_collect_import_reexports` (line 492)
- function: `_is_windows` (line 523)

## Dependency Graph

- **fan_in**: 1
- **fan_out**: 3
- **cycle_group**: 13

## Doc Metrics

- **summary**: Targeted overlay generation with opt-in activation.
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
- enrich/README.md

## Hotspot Score

- score: 2.47

## Side Effects

- filesystem

## Complexity

- branches: 69
- cyclomatic: 70
- loc: 532

## Doc Coverage

- `OverlayPolicy` (class): summary=yes, examples=no — Controls when an overlay is generated and how it is written.
- `OverlayResult` (class): summary=yes, examples=no — Summary of overlay creation for a single module.
- `generate_overlay_for_file` (function): summary=yes, params=ok, examples=no — Generate a .pyi overlay for ``py_file`` when it meets the policy gates.
- `activate_overlays` (function): summary=yes, params=ok, examples=no — Activate overlays by linking or copying into ``stubs_root``.
- `deactivate_all` (function): summary=yes, params=ok, examples=no — Remove overlays under ``stubs_root`` that originated from ``overlays_root``.
- `_overlay_path` (function): summary=yes, params=ok, examples=no — Return the overlay destination path for ``py_file``.
- `_normalized_module_key` (function): summary=yes, params=ok, examples=no — Return a normalized module key used for lookups.
- `_module_name_from_path` (function): summary=yes, params=ok, examples=no — Return the dotted module name for ``py_file``.
- `_collect_star_reexports` (function): summary=yes, params=ok, examples=no — Return candidate names that a star import might re-export.
- `_extract_simple_name` (function): summary=yes, params=ok, examples=no — Extract a plausible leaf identifier from a SCIP symbol string.

## Tags

low-coverage
