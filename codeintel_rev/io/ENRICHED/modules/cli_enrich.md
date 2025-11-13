# cli_enrich.py

## Docstring

```
CLI entrypoint for repo enrichment and targeted overlay generation.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import ast
- from **(absolute)** import json
- from **(absolute)** import logging
- from **collections.abc** import Iterable, Mapping
- from **dataclasses** import asdict, dataclass, field
- from **datetime** import UTC, datetime
- from **fnmatch** import fnmatch
- from **pathlib** import Path
- from **typing** import Any, Protocol, cast
- from **(absolute)** import polars
- from **(absolute)** import typer
- from **codeintel_rev.config_indexer** import index_config_files
- from **codeintel_rev.coverage_ingest** import collect_coverage
- from **codeintel_rev.enrich.ast_indexer** import AstMetricsRow, AstNodeRow, collect_ast_nodes_from_tree, compute_ast_metrics, empty_metrics_row, stable_module_path, write_ast_parquet
- from **codeintel_rev.enrich.graph_builder** import ImportGraph, build_import_graph, write_import_graph
- from **codeintel_rev.enrich.libcst_bridge** import index_module
- from **codeintel_rev.enrich.output_writers** import write_json, write_jsonl, write_markdown_module, write_parquet
- from **codeintel_rev.enrich.ownership** import OwnershipIndex, compute_ownership
- from **codeintel_rev.enrich.pathnorm** import detect_repo_root, module_name_from_path, stable_id_for_path
- from **codeintel_rev.enrich.scip_reader** import Document, SCIPIndex
- from **codeintel_rev.enrich.slices_builder** import build_slice_record, write_slice
- from **codeintel_rev.enrich.stubs_overlay** import OverlayInputs, OverlayPolicy, activate_overlays, deactivate_all, generate_overlay_for_file
- from **codeintel_rev.enrich.tagging** import ModuleTraits, infer_tags, load_rules
- from **codeintel_rev.enrich.tree_sitter_bridge** import build_outline
- from **codeintel_rev.export_resolver** import build_module_name_map, resolve_exports
- from **codeintel_rev.risk_hotspots** import compute_hotspot_score
- from **codeintel_rev.typedness** import FileTypeSignals, collect_type_signals
- from **codeintel_rev.uses_builder** import UseGraph, build_use_graph, write_use_graph
- from **(absolute)** import yaml

## Definitions

- variable: `pl` (line 19)
- variable: `yaml_module` (line 67)
- variable: `LOGGER` (line 70)
- class: `_YamlDumpFn` (line 73)
- variable: `EXPORT_HUB_THRESHOLD` (line 77)
- variable: `OVERLAY_PARAM_THRESHOLD` (line 78)
- variable: `OVERLAY_FAN_IN_THRESHOLD` (line 79)
- variable: `OVERLAY_ERROR_THRESHOLD` (line 80)
- variable: `DEFAULT_MIN_ERRORS` (line 82)
- variable: `DEFAULT_MAX_OVERLAYS` (line 83)
- variable: `DEFAULT_INCLUDE_PUBLIC_DEFS` (line 84)
- variable: `DEFAULT_INJECT_GETATTR_ANY` (line 85)
- variable: `DEFAULT_DRY_RUN` (line 86)
- variable: `DEFAULT_ACTIVATE` (line 87)
- variable: `DEFAULT_DEACTIVATE` (line 88)
- variable: `DEFAULT_USE_TYPE_ERROR_OVERLAYS` (line 89)
- variable: `DEFAULT_EMIT_AST` (line 90)
- variable: `DEFAULT_MAX_FILE_BYTES` (line 91)
- variable: `DEFAULT_OWNER_HISTORY_DAYS` (line 92)
- variable: `DEFAULT_COMMITS_WINDOW` (line 93)
- variable: `DEFAULT_ENABLE_OWNERS` (line 94)
- variable: `DEFAULT_EMIT_SLICES_FLAG` (line 95)
- class: `PipelineOptions` (line 101)
- class: `AnalyticsOptions` (line 115)
- class: `CLIContextState` (line 126)
- variable: `ROOT_OPTION` (line 133)
- variable: `SCIP_OPTION` (line 142)
- variable: `OUT_OPTION` (line 150)
- variable: `PYREFLY_OPTION` (line 156)
- variable: `TAGS_OPTION` (line 164)
- variable: `COVERAGE_OPTION` (line 172)
- variable: `ONLY_OPTION` (line 178)
- variable: `MAX_FILE_BYTES_OPTION` (line 183)
- variable: `OWNERS_OPTION` (line 188)
- variable: `HISTORY_WINDOW_OPTION` (line 193)
- variable: `COMMITS_WINDOW_OPTION` (line 198)
- variable: `EMIT_SLICES_OPTION` (line 203)
- variable: `SLICES_FILTER_OPTION` (line 208)
- variable: `EMIT_AST_OPTION` (line 213)
- variable: `OVERLAYS_CONFIG_OPTION` (line 218)
- variable: `OVERLAYS_SET_OPTION` (line 223)
- variable: `app` (line 231)
- function: `_ensure_state` (line 234)
- function: `global_options` (line 243)
- class: `OverlayCLIOptions` (line 280)
- class: `OverlayContext` (line 296)
- function: `_load_overlay_options` (line 309)
- function: `_read_overlay_config` (line 324)
- function: `_parse_bool` (line 340)
- function: `_resolve_path` (line 353)
- function: `_set_overlay_option` (line 359)
- class: `ScipContext` (line 380)
- class: `ScanInputs` (line 388)
- class: `PipelineContext` (line 401)
- class: `PipelineResult` (line 416)
- function: `_iter_files` (line 431)
- function: `_run_pipeline` (line 443)
- function: `_execute_pipeline` (line 502)
- function: `_scan_modules` (line 509)
- function: `run_all` (line 533)
- function: `run` (line 566)
- function: `scan` (line 576)
- function: `exports` (line 587)
- function: `graph` (line 608)
- function: `uses` (line 616)
- function: `typedness` (line 624)
- function: `doc` (line 632)
- function: `coverage` (line 640)
- function: `config` (line 648)
- function: `hotspots` (line 656)
- function: `overlays` (line 664)
- function: `_build_overlay_context` (line 756)
- function: `_build_module_row` (line 797)
- function: `_scip_symbols_and_edges` (line 898)
- function: `_outline_nodes_for` (line 909)
- function: `_type_error_count` (line 924)
- function: `_coverage_value` (line 929)
- function: `_augment_module_rows` (line 934)
- function: `_build_tag_index` (line 1004)
- function: `_apply_tagging` (line 1018)
- function: `_traits_from_row` (line 1039)
- function: `_build_coverage_rows` (line 1100)
- function: `_build_hotspot_rows` (line 1111)
- function: `_write_exports_outputs` (line 1125)
- function: `_write_graph_outputs` (line 1132)
- function: `_write_uses_output` (line 1137)
- function: `_apply_ownership` (line 1141)
- function: `_write_ownership_output` (line 1170)
- function: `_write_slices_output` (line 1185)
- function: `_write_typedness_output` (line 1216)
- function: `_write_doc_output` (line 1230)
- function: `_write_coverage_output` (line 1244)
- function: `_write_config_output` (line 1248)
- function: `_write_hotspot_output` (line 1252)
- function: `_write_ast_outputs` (line 1256)
- function: `_write_modules_json` (line 1275)
- function: `_write_markdown_modules` (line 1279)
- function: `_write_repo_map` (line 1290)
- function: `_write_symbol_graph` (line 1306)
- function: `_write_tabular_records` (line 1313)
- function: `_collect_ast_artifacts` (line 1320)
- function: `_write_ast_jsonl` (line 1343)
- function: `_normalize_type_signal_map` (line 1348)
- function: `_normalize_metric_map` (line 1364)
- function: `_normalize_path_key` (line 1382)
- function: `_group_configs_by_dir` (line 1386)
- function: `_config_refs_for_row` (line 1397)
- function: `_ancestor_dirs` (line 1413)
- function: `_dir_key_from_path` (line 1428)
- function: `_should_mark_overlay` (line 1435)
- function: `_ensure_package_overlays` (line 1466)
- function: `_normalized_rel_path` (line 1552)
- function: `_write_tag_index` (line 1556)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 18
- **cycle_group**: 23

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 17
- recent churn 90: 17

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

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

## Hotspot

- score: 3.28

## Side Effects

- filesystem

## Complexity

- branches: 177
- cyclomatic: 178
- loc: 1573

## Doc Coverage

- `_YamlDumpFn` (class): summary=no, examples=no
- `PipelineOptions` (class): summary=yes, examples=no — Resolved paths and filters required for pipeline execution.
- `AnalyticsOptions` (class): summary=yes, examples=no — Optional analytics toggles shared across commands.
- `CLIContextState` (class): summary=yes, examples=no — CLI-scoped state shared between commands.
- `_ensure_state` (function): summary=no, examples=no
- `global_options` (function): summary=yes, params=mismatch, examples=no — Capture shared pipeline + analytics options for all commands.
- `OverlayCLIOptions` (class): summary=yes, examples=no — Mutable overlay generation options parsed from CLI/config.
- `OverlayContext` (class): summary=yes, examples=no — Aggregated context used during overlay generation.
- `_load_overlay_options` (function): summary=no, examples=no
- `_read_overlay_config` (function): summary=no, examples=no

## Tags

low-coverage
