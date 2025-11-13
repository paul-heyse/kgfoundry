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
- class: `OverlayInputs` (line 41)
- class: `OverlayRenderContext` (line 50)
- function: `generate_overlay_for_file` (line 61)
- function: `activate_overlays` (line 181)
- function: `deactivate_all` (line 230)
- function: `_overlay_path` (line 268)
- function: `_normalized_module_key` (line 292)
- function: `_module_name_from_path` (line 312)
- function: `_collect_star_reexports` (line 336)
- function: `_extract_simple_name` (line 367)
- function: `_build_overlay_text` (line 394)
- function: `_render_star_exports` (line 441)
- function: `_render_public_defs` (line 466)
- function: `_collect_import_reexports` (line 497)
- function: `_is_windows` (line 528)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 3
- **cycle_group**: 10

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 10
- recent churn 90: 10

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

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
- enrich/PLAYBOOK.md
- enrich/README.md

## Hotspot

- score: 2.46

## Side Effects

- filesystem

## Complexity

- branches: 68
- cyclomatic: 69
- loc: 537

## Doc Coverage

- `OverlayPolicy` (class): summary=yes, examples=no — Controls when an overlay is generated and how it is written.
- `OverlayResult` (class): summary=yes, examples=no — Summary of overlay creation for a single module.
- `OverlayInputs` (class): summary=yes, examples=no — Runtime inputs influencing overlay generation.
- `OverlayRenderContext` (class): summary=yes, examples=no — Bundle of values required to render overlay text.
- `generate_overlay_for_file` (function): summary=yes, params=ok, examples=no — Generate a .pyi overlay for ``py_file`` when it meets the policy gates.
- `activate_overlays` (function): summary=yes, params=ok, examples=no — Activate overlays by linking or copying into ``stubs_root``.
- `deactivate_all` (function): summary=yes, params=ok, examples=no — Remove overlays under ``stubs_root`` that originated from ``overlays_root``.
- `_overlay_path` (function): summary=yes, params=ok, examples=no — Return the overlay destination path for ``py_file``.
- `_normalized_module_key` (function): summary=yes, params=ok, examples=no — Return a normalized module key used for lookups.
- `_module_name_from_path` (function): summary=yes, params=ok, examples=no — Return the dotted module name for ``py_file``.

## Tags

low-coverage
