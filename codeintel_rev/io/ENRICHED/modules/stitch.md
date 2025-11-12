# enrich/stitch.py

## Docstring

```
Stitch LibCST + SCIP + tagging outputs into enriched module records.
```

## Imports

- from **__future__** import annotations
- from **collections** import defaultdict
- from **collections.abc** import Iterable, Mapping
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import Any
- from **codeintel_rev.enrich.scip_reader** import SCIPIndex

## Definitions

- function: `_module_name_from_path` (line 17)
- function: `_package_root` (line 32)
- function: `_candidate_init_path` (line 37)
- function: `_public_names_from_row` (line 41)
- function: `_resolve_absolute_module` (line 56)
- function: `_possible_module_names` (line 68)
- function: `_target_path` (line 77)
- function: `_import_targets` (line 94)
- class: `_Graph` (line 122)
- class: `_GraphContext` (line 128)
- function: `_build_import_graph` (line 137)
- function: `_process_imports_for_row` (line 155)
- function: `_add_edges` (line 171)
- function: `_module_rows_by_name` (line 189)
- function: `_tarjan_scc` (line 205)
- function: `_module_rows_by_name` (line 244)
- function: `_resolve_star_imports` (line 263)
- function: `stitch_records` (line 296)

## Dependency Graph

- **fan_in**: 1
- **fan_out**: 2
- **cycle_group**: 2

## Declared Exports (__all__)

stitch_records

## Tags

public-api
