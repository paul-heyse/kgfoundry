# cli_enrich.py

## Docstring

```
CLI entrypoint for repo enrichment and targeted overlay generation.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Iterable, Mapping
- from **dataclasses** import dataclass
- from **datetime** import UTC, datetime
- from **fnmatch** import fnmatch
- from **pathlib** import Path
- from **typing** import Annotated, Any
- from **(absolute)** import polars
- from **(absolute)** import typer
- from **codeintel_rev.config_indexer** import index_config_files
- from **codeintel_rev.coverage_ingest** import collect_coverage
- from **codeintel_rev.enrich.libcst_bridge** import index_module
- from **codeintel_rev.enrich.output_writers** import write_json, write_jsonl, write_markdown_module
- from **codeintel_rev.enrich.scip_reader** import Document, SCIPIndex
- from **codeintel_rev.enrich.stubs_overlay** import OverlayPolicy, activate_overlays, deactivate_all, generate_overlay_for_file
- from **codeintel_rev.enrich.tagging** import ModuleTraits, infer_tags, load_rules
- from **codeintel_rev.enrich.tree_sitter_bridge** import build_outline
- from **codeintel_rev.export_resolver** import build_module_name_map, resolve_exports
- from **codeintel_rev.graph_builder** import ImportGraph, build_import_graph, write_import_graph
- from **codeintel_rev.risk_hotspots** import compute_hotspot_score
- from **codeintel_rev.typedness** import FileTypeSignals, collect_type_signals
- from **codeintel_rev.uses_builder** import UseGraph, build_use_graph, write_use_graph
- from **(absolute)** import yaml

## Definitions

- variable: `pl` (line 16)
- variable: `yaml_module` (line 42)
- variable: `EXPORT_HUB_THRESHOLD` (line 44)
- variable: `OVERLAY_PARAM_THRESHOLD` (line 45)
- variable: `OVERLAY_FAN_IN_THRESHOLD` (line 46)
- variable: `OVERLAY_ERROR_THRESHOLD` (line 47)
- variable: `ROOT` (line 49)
- variable: `SCIP` (line 50)
- variable: `OUT` (line 51)
- variable: `PYREFLY` (line 56)
- variable: `TAGS` (line 61)
- variable: `COVERAGE_XML` (line 62)
- variable: `OnlyPatternsOption` (line 67)
- variable: `DEFAULT_MIN_ERRORS` (line 75)
- variable: `DEFAULT_MAX_OVERLAYS` (line 76)
- variable: `DEFAULT_INCLUDE_PUBLIC_DEFS` (line 77)
- variable: `DEFAULT_INJECT_GETATTR_ANY` (line 78)
- variable: `DEFAULT_DRY_RUN` (line 79)
- variable: `DEFAULT_ACTIVATE` (line 80)
- variable: `DEFAULT_DEACTIVATE` (line 81)
- variable: `DEFAULT_USE_TYPE_ERROR_OVERLAYS` (line 82)
- variable: `STUBS` (line 84)
- variable: `OVERLAYS_ROOT` (line 89)
- variable: `MIN_ERRORS` (line 94)
- variable: `MAX_OVERLAYS` (line 99)
- variable: `INCLUDE_PUBLIC_DEFS` (line 104)
- variable: `INJECT_GETATTR_ANY` (line 109)
- variable: `DRY_RUN` (line 114)
- variable: `ACTIVATE` (line 119)
- variable: `DEACTIVATE` (line 124)
- variable: `TYPE_ERROR_OVERLAYS` (line 129)
- variable: `app` (line 135)
- class: `ScipContext` (line 139)
- class: `ScanInputs` (line 147)
- class: `PipelineResult` (line 157)
- function: `_iter_files` (line 171)
- function: `_run_pipeline` (line 183)
- function: `run_all` (line 255)
- function: `scan` (line 286)
- function: `exports` (line 309)
- function: `graph` (line 333)
- function: `uses` (line 357)
- function: `typedness` (line 381)
- function: `doc` (line 405)
- function: `coverage` (line 429)
- function: `config` (line 453)
- function: `hotspots` (line 477)
- function: `overlays` (line 501)
- function: `_build_module_row` (line 616)
- function: `_augment_module_rows` (line 691)
- function: `_build_tag_index` (line 761)
- function: `_apply_tagging` (line 775)
- function: `_traits_from_row` (line 787)
- function: `_build_coverage_rows` (line 839)
- function: `_build_hotspot_rows` (line 850)
- function: `_write_exports_outputs` (line 864)
- function: `_write_graph_outputs` (line 871)
- function: `_write_uses_output` (line 876)
- function: `_write_typedness_output` (line 880)
- function: `_write_doc_output` (line 894)
- function: `_write_coverage_output` (line 908)
- function: `_write_config_output` (line 912)
- function: `_write_hotspot_output` (line 916)
- function: `_write_modules_json` (line 920)
- function: `_write_markdown_modules` (line 924)
- function: `_write_repo_map` (line 935)
- function: `_write_symbol_graph` (line 950)
- function: `_write_tabular_records` (line 957)
- function: `_normalize_type_signal_map` (line 964)
- function: `_normalize_metric_map` (line 980)
- function: `_normalize_path_key` (line 998)
- function: `_group_configs_by_dir` (line 1002)
- function: `_config_refs_for_row` (line 1013)
- function: `_ancestor_dirs` (line 1029)
- function: `_dir_key_from_path` (line 1044)
- function: `_should_mark_overlay` (line 1051)
- function: `_ensure_package_overlays` (line 1081)
- function: `_normalized_rel_path` (line 1165)
- function: `_write_tag_index` (line 1169)

## Dependency Graph

- **fan_in**: 0
- **fan_out**: 14
- **cycle_group**: 18

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

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Hotspot Score

- score: 3.08

## Side Effects

- filesystem

## Complexity

- branches: 123
- cyclomatic: 124
- loc: 1182

## Doc Coverage

- `ScipContext` (class): summary=yes, examples=no — Cache of SCIP lookups used during scanning.
- `ScanInputs` (class): summary=yes, examples=no — Bundle of contextual inputs used during module row construction.
- `PipelineResult` (class): summary=yes, examples=no — Aggregate artifact bundle produced by a pipeline run.
- `_iter_files` (function): summary=no, examples=no
- `_run_pipeline` (function): summary=no, examples=no
- `run_all` (function): summary=yes, params=mismatch, examples=no — Run the full enrichment pipeline and emit all artifacts.
- `scan` (function): summary=yes, params=mismatch, examples=no — Backward-compatible alias for ``all``.
- `exports` (function): summary=yes, params=mismatch, examples=no — Emit modules.jsonl, repo map, tag index, and Markdown module sheets.
- `graph` (function): summary=yes, params=mismatch, examples=no — Emit symbol and import graph artifacts.
- `uses` (function): summary=yes, params=mismatch, examples=no — Emit the definition-to-use graph derived from SCIP.

## Tags

low-coverage
