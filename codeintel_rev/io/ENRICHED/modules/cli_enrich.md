# cli_enrich.py

## Docstring

```
CLI entrypoint for repo enrichment and targeted overlay generation.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Iterable, Mapping, MutableMapping
- from **dataclasses** import dataclass
- from **datetime** import UTC, datetime
- from **pathlib** import Path
- from **typing** import Any
- from **(absolute)** import typer
- from **codeintel_rev.enrich.libcst_bridge** import index_module
- from **codeintel_rev.enrich.output_writers** import write_json, write_jsonl, write_markdown_module
- from **codeintel_rev.enrich.scip_reader** import Document, SCIPIndex
- from **codeintel_rev.enrich.stubs_overlay** import OverlayPolicy, activate_overlays, deactivate_all, generate_overlay_for_file
- from **codeintel_rev.enrich.tagging** import ModuleTraits, infer_tags, load_rules
- from **codeintel_rev.enrich.tree_sitter_bridge** import build_outline
- from **codeintel_rev.enrich.type_integration** import TypeSummary, collect_pyrefly, collect_pyright
- from **codeintel_rev.export_resolver** import build_module_name_map, resolve_exports
- from **codeintel_rev.graph_builder** import build_import_graph, write_import_graph
- from **codeintel_rev.uses_builder** import build_use_graph, write_use_graph
- from **(absolute)** import yaml

## Definitions

- variable: `yaml_module` (line 33)
- variable: `EXPORT_HUB_THRESHOLD` (line 35)
- variable: `ROOT` (line 37)
- variable: `SCIP` (line 38)
- variable: `OUT` (line 39)
- variable: `PYREFLY` (line 44)
- variable: `TAGS` (line 49)
- variable: `DEFAULT_MIN_ERRORS` (line 51)
- variable: `DEFAULT_MAX_OVERLAYS` (line 52)
- variable: `DEFAULT_INCLUDE_PUBLIC_DEFS` (line 53)
- variable: `DEFAULT_INJECT_GETATTR_ANY` (line 54)
- variable: `DEFAULT_DRY_RUN` (line 55)
- variable: `DEFAULT_ACTIVATE` (line 56)
- variable: `DEFAULT_DEACTIVATE` (line 57)
- variable: `DEFAULT_USE_TYPE_ERROR_OVERLAYS` (line 58)
- variable: `STUBS` (line 60)
- variable: `OVERLAYS_ROOT` (line 65)
- variable: `MIN_ERRORS` (line 70)
- variable: `MAX_OVERLAYS` (line 75)
- variable: `INCLUDE_PUBLIC_DEFS` (line 80)
- variable: `INJECT_GETATTR_ANY` (line 85)
- variable: `DRY_RUN` (line 90)
- variable: `ACTIVATE` (line 95)
- variable: `DEACTIVATE` (line 100)
- variable: `TYPE_ERROR_OVERLAYS` (line 105)
- variable: `app` (line 111)
- class: `ScipContext` (line 115)
- class: `TypeSignals` (line 123)
- function: `_iter_files` (line 130)
- function: `scan` (line 138)
- function: `overlays` (line 189)
- function: `_build_module_row` (line 302)
- function: `_augment_module_rows` (line 383)
- function: `_ensure_package_overlays` (line 423)
- function: `_max_type_errors` (line 507)
- function: `_normalized_rel_path` (line 516)
- function: `_write_tag_index` (line 520)
- function: `_register_type_count` (line 531)

## Dependency Graph

- **fan_in**: 0
- **fan_out**: 11
- **cycle_group**: 12

## Doc Metrics

- **summary**: CLI entrypoint for repo enrichment and targeted overlay generation.
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

- branches: 44
- cyclomatic: 45
- loc: 549

## Doc Coverage

- `ScipContext` (class): summary=yes, examples=no — Cache of SCIP lookups used during scanning.
- `TypeSignals` (class): summary=yes, examples=no — Pyright/Pyrefly summaries.
- `_iter_files` (function): summary=no, examples=no
- `scan` (function): summary=yes, params=mismatch, examples=no — Build LibCST/SCIP/type-signal enriched artifacts.
- `overlays` (function): summary=yes, params=mismatch, examples=no — Generate targeted overlays and optionally activate them into the stub path.
- `_build_module_row` (function): summary=no, examples=no
- `_augment_module_rows` (function): summary=yes, params=mismatch, examples=no — Attach graph/usage/export metadata and emit module artifacts.
- `_ensure_package_overlays` (function): summary=yes, params=ok, examples=no — Ensure package ``__init__`` overlays exist for ancestors of ``rel_path``.
- `_max_type_errors` (function): summary=no, examples=no
- `_normalized_rel_path` (function): summary=no, examples=no

## Tags

cli
