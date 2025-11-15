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

- variable: `DEFAULT_EXPORT_HUB_THRESHOLD` (line 15)
- class: `OverlayPolicy` (line 19)
- class: `OverlayResult` (line 34)
- class: `OverlayInputs` (line 44)
- class: `OverlayRenderContext` (line 54)
- class: `OverlayDecisionInputs` (line 66)
- function: `_should_generate_overlay` (line 75)
- function: `generate_overlay_for_file` (line 94)
- function: `activate_overlays` (line 217)
- function: `deactivate_all` (line 266)
- function: `_overlay_path` (line 304)
- function: `_normalized_module_key` (line 328)
- function: `_module_name_from_path` (line 348)
- function: `_collect_star_reexports` (line 372)
- function: `_extract_simple_name` (line 403)
- function: `_build_overlay_text` (line 430)
- function: `_render_star_exports` (line 477)
- function: `_render_public_defs` (line 502)
- function: `_collect_import_reexports` (line 533)
- function: `_is_windows` (line 564)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 3
- **cycle_group**: 104

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 14
- recent churn 90: 14

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
- loc: 573

## Doc Coverage

- `OverlayPolicy` (class): summary=yes, examples=no — Controls when an overlay is generated and how it is written.
- `OverlayResult` (class): summary=yes, examples=no — Summary of overlay creation for a single module.
- `OverlayInputs` (class): summary=yes, examples=no — Runtime inputs influencing overlay generation.
- `OverlayRenderContext` (class): summary=yes, examples=no — Bundle of values required to render overlay text.
- `OverlayDecisionInputs` (class): summary=yes, examples=no — Data needed to decide whether an overlay should be generated.
- `_should_generate_overlay` (function): summary=no, examples=no
- `generate_overlay_for_file` (function): summary=yes, params=ok, examples=no — Generate a .pyi overlay for ``py_file`` when it meets the policy gates.
- `activate_overlays` (function): summary=yes, params=ok, examples=no — Activate overlays by linking or copying into ``stubs_root``.
- `deactivate_all` (function): summary=yes, params=ok, examples=no — Remove overlays under ``stubs_root`` that originated from ``overlays_root``.
- `_overlay_path` (function): summary=yes, params=ok, examples=no — Return the overlay destination path for ``py_file``.

## Tags

low-coverage
