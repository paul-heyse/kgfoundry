# enrich/stubs_overlay.py

## Docstring

```
Overlay generation utilities for the enrichment CLI.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Iterable, Mapping
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **codeintel_rev.enrich.libcst_bridge** import DefEntry, ImportEntry, ModuleIndex, index_module
- from **codeintel_rev.enrich.output_writers** import write_json
- from **codeintel_rev.enrich.scip_reader** import Document, SCIPIndex

## Definitions

- class: `OverlayResult` (line 16)
- function: `generate_overlay_for_file` (line 24)
- function: `_infer_repo_root` (line 123)
- function: `_safe_relative` (line 130)
- function: `_module_name_from_path` (line 137)
- function: `_collect_star_reexports` (line 149)
- function: `_resolve_target_module` (line 172)
- function: `_names_from_scip` (line 185)
- function: `_candidate_file_paths_for_module` (line 209)
- function: `_simple_name_from_scip_symbol` (line 233)
- function: `_is_private` (line 244)
- function: `_is_public_def` (line 248)
- function: `_pyi_header` (line 252)
- function: `_build_overlay_text` (line 262)
- function: `_write_sidecar` (line 298)

## Tags

overlay-needed
