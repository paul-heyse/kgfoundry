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
- function: `generate_overlay_for_file` (line 40)
- function: `activate_overlays` (line 157)
- function: `deactivate_all` (line 206)
- function: `_overlay_path` (line 244)
- function: `_normalized_module_key` (line 267)
- function: `_module_name_from_path` (line 287)
- function: `_collect_star_reexports` (line 308)
- function: `_extract_simple_name` (line 336)
- function: `_build_overlay_text` (line 363)
- function: `_render_star_exports` (line 422)
- function: `_render_public_defs` (line 444)
- function: `_collect_import_reexports` (line 473)
- function: `_is_windows` (line 504)

## Dependency Graph

- **fan_in**: 1
- **fan_out**: 3
- **cycle_group**: 5
