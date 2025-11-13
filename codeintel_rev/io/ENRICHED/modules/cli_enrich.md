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
- class: `OverlayCLIOptions` (line 282)
- class: `OverlayContext` (line 298)
- function: `_load_overlay_options` (line 311)
- function: `_read_overlay_config` (line 326)
- function: `_parse_bool` (line 342)
- function: `_resolve_path` (line 355)
- function: `_parse_int_option` (line 361)
- function: `_parse_path_option` (line 374)
- function: `_set_overlay_option` (line 383)
- class: `ScipContext` (line 409)
- class: `ScanInputs` (line 417)
- class: `PipelineContext` (line 430)
- class: `PipelineResult` (line 445)
- function: `_iter_files` (line 460)
- function: `_run_pipeline` (line 472)
- function: `_execute_pipeline` (line 533)
- function: `_scan_modules` (line 540)
- function: `run_all` (line 564)
- function: `run` (line 597)
- function: `scan` (line 607)
- function: `exports` (line 618)
- function: `graph` (line 639)
- function: `uses` (line 647)
- function: `typedness` (line 655)
- function: `doc` (line 663)
- function: `coverage` (line 671)
- function: `config` (line 679)
- function: `hotspots` (line 687)
- function: `overlays` (line 695)
- function: `_build_overlay_context` (line 826)
- function: `_build_module_row` (line 870)
- function: `_scip_symbols_and_edges` (line 971)
- function: `_outline_nodes_for` (line 982)
- function: `_type_error_count` (line 997)
- function: `_coverage_value` (line 1002)
- function: `_augment_module_rows` (line 1007)
- function: `_build_tag_index` (line 1077)
- function: `_apply_tagging` (line 1091)
- function: `_traits_from_row` (line 1112)
- function: `_build_coverage_rows` (line 1173)
- function: `_build_hotspot_rows` (line 1184)
- function: `_write_exports_outputs` (line 1198)
- function: `_write_graph_outputs` (line 1205)
- function: `_write_uses_output` (line 1210)
- function: `_apply_ownership` (line 1214)
- function: `_write_ownership_output` (line 1243)
- function: `_write_slices_output` (line 1258)
- function: `_write_typedness_output` (line 1289)
- function: `_write_doc_output` (line 1303)
- function: `_write_coverage_output` (line 1317)
- function: `_write_config_output` (line 1321)
- function: `_write_hotspot_output` (line 1325)
- function: `_write_ast_outputs` (line 1329)
- function: `_write_modules_json` (line 1348)
- function: `_write_markdown_modules` (line 1352)
- function: `_write_repo_map` (line 1363)
- function: `_write_symbol_graph` (line 1379)
- function: `_write_tabular_records` (line 1386)
- function: `_collect_ast_artifacts` (line 1393)
- function: `_write_ast_jsonl` (line 1416)
- function: `_normalize_type_signal_map` (line 1421)
- function: `_normalize_metric_map` (line 1437)
- function: `_normalize_path_key` (line 1455)
- function: `_group_configs_by_dir` (line 1459)
- function: `_config_refs_for_row` (line 1470)
- function: `_ancestor_dirs` (line 1486)
- function: `_dir_key_from_path` (line 1501)
- function: `_should_mark_overlay` (line 1508)
- function: `_ensure_package_overlays` (line 1538)
- function: `_normalized_rel_path` (line 1624)
- function: `_write_tag_index` (line 1628)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 18
- **cycle_group**: 24

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 21
- recent churn 90: 21

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

- score: 3.29

## Side Effects

- filesystem

## Complexity

- branches: 183
- cyclomatic: 184
- loc: 1645

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
