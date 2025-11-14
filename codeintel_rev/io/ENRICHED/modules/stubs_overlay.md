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

- variable: `DEFAULT_EXPORT_HUB_THRESHOLD` (line 16)
- class: `OverlayPolicy` (line 20)
- class: `OverlayResult` (line 35)
- class: `OverlayInputs` (line 45)
- class: `OverlayRenderContext` (line 55)
- function: `generate_overlay_for_file` (line 66)
- function: `activate_overlays` (line 194)
- function: `deactivate_all` (line 243)
- function: `_overlay_path` (line 281)
- function: `_normalized_module_key` (line 305)
- function: `_module_name_from_path` (line 325)
- function: `_collect_star_reexports` (line 349)
- function: `_extract_simple_name` (line 380)
- function: `_build_overlay_text` (line 407)
- function: `_render_star_exports` (line 454)
- function: `_render_public_defs` (line 479)
- function: `_collect_import_reexports` (line 510)
- function: `_is_windows` (line 541)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 3
- **cycle_group**: 89

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 12
- recent churn 90: 12

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

- score: 2.48

## Side Effects

- filesystem

## Complexity

- branches: 72
- cyclomatic: 73
- loc: 550

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
