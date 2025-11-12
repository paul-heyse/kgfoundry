# cli_enrich.py

## Docstring

```
CLI entrypoint for repo enrichment and targeted overlay generation.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Iterable, Mapping, MutableMapping
- from **dataclasses** import asdict, dataclass
- from **datetime** import UTC, datetime
- from **pathlib** import Path
- from **typing** import Any
- from **(absolute)** import typer
- from **codeintel_rev.enrich.libcst_bridge** import index_module
- from **codeintel_rev.enrich.output_writers** import write_json, write_jsonl, write_markdown_module
- from **codeintel_rev.enrich.scip_reader** import Document, SCIPIndex
- from **codeintel_rev.enrich.stitch** import stitch_records
- from **codeintel_rev.enrich.stubs_overlay** import OverlayPolicy, activate_overlays, deactivate_all, generate_overlay_for_file
- from **codeintel_rev.enrich.tagging** import ModuleTraits, infer_tags, load_rules
- from **codeintel_rev.enrich.tree_sitter_bridge** import build_outline
- from **codeintel_rev.enrich.type_integration** import TypeSummary, collect_pyrefly, collect_pyright
- from **(absolute)** import yaml

## Definitions

- variable: `yaml_module` (line 31)
- variable: `EXPORT_HUB_THRESHOLD` (line 33)
- variable: `ROOT` (line 35)
- variable: `SCIP` (line 36)
- variable: `OUT` (line 37)
- variable: `PYREFLY` (line 42)
- variable: `TAGS` (line 47)
- variable: `DEFAULT_MIN_ERRORS` (line 49)
- variable: `DEFAULT_MAX_OVERLAYS` (line 50)
- variable: `DEFAULT_INCLUDE_PUBLIC_DEFS` (line 51)
- variable: `DEFAULT_INJECT_GETATTR_ANY` (line 52)
- variable: `DEFAULT_DRY_RUN` (line 53)
- variable: `DEFAULT_ACTIVATE` (line 54)
- variable: `DEFAULT_DEACTIVATE` (line 55)
- variable: `DEFAULT_USE_TYPE_ERROR_OVERLAYS` (line 56)
- variable: `STUBS` (line 58)
- variable: `OVERLAYS_ROOT` (line 63)
- variable: `MIN_ERRORS` (line 68)
- variable: `MAX_OVERLAYS` (line 73)
- variable: `INCLUDE_PUBLIC_DEFS` (line 78)
- variable: `INJECT_GETATTR_ANY` (line 83)
- variable: `DRY_RUN` (line 88)
- variable: `ACTIVATE` (line 93)
- variable: `DEACTIVATE` (line 98)
- variable: `TYPE_ERROR_OVERLAYS` (line 103)
- variable: `app` (line 109)
- class: `ModuleRecord` (line 113)
- class: `ScipContext` (line 130)
- class: `TypeSignals` (line 138)
- function: `_iter_files` (line 145)
- function: `scan` (line 153)
- function: `overlays` (line 208)
- function: `_build_module_row` (line 321)
- function: `_ensure_package_overlays` (line 394)
- function: `_max_type_errors` (line 478)
- function: `_normalized_rel_path` (line 487)
- function: `_write_tag_index` (line 491)
- function: `_register_type_count` (line 502)

## Dependency Graph

- **fan_in**: 0
- **fan_out**: 9
- **cycle_group**: 9

## Tags

cli
