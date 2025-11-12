# cli_enrich.py

## Docstring

```
CLI entrypoint for repo enrichment and targeted overlay generation.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import ast
- from **(absolute)** import logging
- from **collections.abc** import Iterable, Mapping
- from **dataclasses** import dataclass
- from **datetime** import UTC, datetime
- from **fnmatch** import fnmatch
- from **pathlib** import Path
- from **typing** import Annotated, Any, Protocol, cast
- from **(absolute)** import polars
- from **(absolute)** import typer
- from **codeintel_rev.config_indexer** import index_config_files
- from **codeintel_rev.coverage_ingest** import collect_coverage
- from **codeintel_rev.enrich.ast_indexer** import AstMetricsRow, AstNodeRow, collect_ast_nodes_from_tree, compute_ast_metrics, empty_metrics_row, stable_module_path, write_ast_parquet
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

- variable: `pl` (line 18)
- variable: `yaml_module` (line 53)
- variable: `LOGGER` (line 56)
- class: `_YamlDumpFn` (line 59)
- variable: `EXPORT_HUB_THRESHOLD` (line 63)
- variable: `OVERLAY_PARAM_THRESHOLD` (line 64)
- variable: `OVERLAY_FAN_IN_THRESHOLD` (line 65)
- variable: `OVERLAY_ERROR_THRESHOLD` (line 66)
- variable: `ROOT` (line 68)
- variable: `SCIP` (line 69)
- variable: `OUT` (line 70)
- variable: `PYREFLY` (line 75)
- variable: `TAGS` (line 80)
- variable: `COVERAGE_XML` (line 81)
- variable: `OnlyPatternsOption` (line 86)
- variable: `DEFAULT_MIN_ERRORS` (line 94)
- variable: `DEFAULT_MAX_OVERLAYS` (line 95)
- variable: `DEFAULT_INCLUDE_PUBLIC_DEFS` (line 96)
- variable: `DEFAULT_INJECT_GETATTR_ANY` (line 97)
- variable: `DEFAULT_DRY_RUN` (line 98)
- variable: `DEFAULT_ACTIVATE` (line 99)
- variable: `DEFAULT_DEACTIVATE` (line 100)
- variable: `DEFAULT_USE_TYPE_ERROR_OVERLAYS` (line 101)
- variable: `DEFAULT_EMIT_AST` (line 102)
- variable: `STUBS` (line 104)
- variable: `OVERLAYS_ROOT` (line 109)
- variable: `MIN_ERRORS` (line 114)
- variable: `MAX_OVERLAYS` (line 119)
- variable: `INCLUDE_PUBLIC_DEFS` (line 124)
- variable: `INJECT_GETATTR_ANY` (line 129)
- variable: `DRY_RUN` (line 134)
- variable: `ACTIVATE` (line 139)
- variable: `DEACTIVATE` (line 144)
- variable: `TYPE_ERROR_OVERLAYS` (line 149)
- variable: `app` (line 155)
- class: `ScipContext` (line 159)
- class: `ScanInputs` (line 167)
- class: `PipelineResult` (line 177)
- function: `_iter_files` (line 191)
- function: `_run_pipeline` (line 204)
- function: `run_all` (line 277)
- function: `scan` (line 317)
- function: `exports` (line 349)
- function: `graph` (line 374)
- function: `uses` (line 399)
- function: `typedness` (line 424)
- function: `doc` (line 449)
- function: `coverage` (line 474)
- function: `config` (line 499)
- function: `hotspots` (line 524)
- function: `overlays` (line 549)
- function: `_build_module_row` (line 664)
- function: `_augment_module_rows` (line 739)
- function: `_build_tag_index` (line 809)
- function: `_apply_tagging` (line 823)
- function: `_traits_from_row` (line 844)
- function: `_build_coverage_rows` (line 905)
- function: `_build_hotspot_rows` (line 916)
- function: `_write_exports_outputs` (line 930)
- function: `_write_graph_outputs` (line 937)
- function: `_write_uses_output` (line 942)
- function: `_write_typedness_output` (line 946)
- function: `_write_doc_output` (line 960)
- function: `_write_coverage_output` (line 974)
- function: `_write_config_output` (line 978)
- function: `_write_hotspot_output` (line 982)
- function: `_write_ast_outputs` (line 986)
- function: `_write_modules_json` (line 1007)
- function: `_write_markdown_modules` (line 1011)
- function: `_write_repo_map` (line 1022)
- function: `_write_symbol_graph` (line 1037)
- function: `_write_tabular_records` (line 1044)
- function: `_collect_ast_artifacts` (line 1051)
- function: `_write_ast_jsonl` (line 1074)
- function: `_normalize_type_signal_map` (line 1079)
- function: `_normalize_metric_map` (line 1095)
- function: `_normalize_path_key` (line 1113)
- function: `_group_configs_by_dir` (line 1117)
- function: `_config_refs_for_row` (line 1128)
- function: `_ancestor_dirs` (line 1144)
- function: `_dir_key_from_path` (line 1159)
- function: `_should_mark_overlay` (line 1166)
- function: `_ensure_package_overlays` (line 1197)
- function: `_normalized_rel_path` (line 1281)
- function: `_write_tag_index` (line 1285)

## Dependency Graph

- **fan_in**: 0
- **fan_out**: 15
- **cycle_group**: 19

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

- score: 3.12

## Side Effects

- filesystem

## Complexity

- branches: 131
- cyclomatic: 132
- loc: 1302

## Doc Coverage

- `_YamlDumpFn` (class): summary=no, examples=no
- `ScipContext` (class): summary=yes, examples=no — Cache of SCIP lookups used during scanning.
- `ScanInputs` (class): summary=yes, examples=no — Bundle of contextual inputs used during module row construction.
- `PipelineResult` (class): summary=yes, examples=no — Aggregate artifact bundle produced by a pipeline run.
- `_iter_files` (function): summary=no, examples=no
- `_run_pipeline` (function): summary=no, examples=no
- `run_all` (function): summary=yes, params=mismatch, examples=no — Run the full enrichment pipeline and emit all artifacts.
- `scan` (function): summary=yes, params=mismatch, examples=no — Backward-compatible alias for ``all``.
- `exports` (function): summary=yes, params=mismatch, examples=no — Emit modules.jsonl, repo map, tag index, and Markdown module sheets.
- `graph` (function): summary=yes, params=mismatch, examples=no — Emit symbol and import graph artifacts.

## Tags

low-coverage
