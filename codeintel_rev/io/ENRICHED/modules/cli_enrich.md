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
- from **(absolute)** import time
- from **collections.abc** import Iterable, Iterator, Mapping, Sequence
- from **contextlib** import contextmanager
- from **dataclasses** import asdict, dataclass, field, replace
- from **datetime** import UTC, datetime
- from **fnmatch** import fnmatch
- from **pathlib** import Path
- from **typing** import Annotated, Any, Protocol, cast
- from **(absolute)** import typer
- from **codeintel_rev.config_indexer** import index_config_files
- from **codeintel_rev.coverage_ingest** import collect_coverage
- from **codeintel_rev.enrich.ast_indexer** import AstMetricsRow, AstNodeRow, collect_ast_nodes_from_tree, compute_ast_metrics, empty_metrics_row, stable_module_path, write_ast_parquet
- from **codeintel_rev.enrich.duckdb_store** import DuckConn, ingest_modules_jsonl
- from **codeintel_rev.enrich.errors** import IndexingError, IngestError, StageError, TaggingError, TypeSignalError
- from **codeintel_rev.enrich.graph_builder** import ImportGraph, build_import_graph, write_import_graph
- from **codeintel_rev.enrich.libcst_bridge** import ModuleIndex, index_module
- from **codeintel_rev.enrich.models** import ModuleRecord
- from **codeintel_rev.enrich.output_writers** import write_json, write_jsonl, write_markdown_module, write_parquet, write_parquet_dataset
- from **codeintel_rev.enrich.ownership** import OwnershipIndex, compute_ownership
- from **codeintel_rev.enrich.pathnorm** import detect_repo_root, module_name_from_path, stable_id_for_path
- from **codeintel_rev.enrich.scip_reader** import Document, SCIPIndex
- from **codeintel_rev.enrich.slices_builder** import build_slice_record, write_slice
- from **codeintel_rev.enrich.stubs_overlay** import OverlayInputs, OverlayPolicy, activate_overlays, deactivate_all, generate_overlay_for_file
- from **codeintel_rev.enrich.tagging** import ModuleTraits, infer_tags, load_rules
- from **codeintel_rev.enrich.tree_sitter_bridge** import build_outline
- from **codeintel_rev.enrich.validators** import ModuleRecordModel
- from **codeintel_rev.export_resolver** import build_module_name_map, resolve_exports
- from **codeintel_rev.risk_hotspots** import compute_hotspot_score
- from **codeintel_rev.typedness** import FileTypeSignals, collect_type_signals
- from **codeintel_rev.uses_builder** import UseGraph, build_use_graph, write_use_graph
- from **(absolute)** import yaml

## Definitions

- variable: `yaml_module` (line 75)
- function: `_yaml_errors` (line 78)
- variable: `YAML_ERRORS` (line 91)
- variable: `LOGGER` (line 94)
- function: `_format_stage_meta` (line 97)
- function: `_stage_span` (line 103)
- class: `_YamlDumpFn` (line 143)
- variable: `EXPORT_HUB_THRESHOLD` (line 147)
- variable: `OVERLAY_PARAM_THRESHOLD` (line 148)
- variable: `OVERLAY_FAN_IN_THRESHOLD` (line 149)
- variable: `OVERLAY_ERROR_THRESHOLD` (line 150)
- variable: `DEFAULT_MIN_ERRORS` (line 152)
- variable: `DEFAULT_MAX_OVERLAYS` (line 153)
- variable: `DEFAULT_INCLUDE_PUBLIC_DEFS` (line 154)
- variable: `DEFAULT_INJECT_GETATTR_ANY` (line 155)
- variable: `DEFAULT_DRY_RUN` (line 156)
- variable: `DEFAULT_ACTIVATE` (line 157)
- variable: `DEFAULT_DEACTIVATE` (line 158)
- variable: `DEFAULT_USE_TYPE_ERROR_OVERLAYS` (line 159)
- variable: `DEFAULT_EMIT_AST` (line 160)
- variable: `DEFAULT_MAX_FILE_BYTES` (line 161)
- variable: `DEFAULT_OWNER_HISTORY_DAYS` (line 162)
- variable: `DEFAULT_COMMITS_WINDOW` (line 163)
- variable: `DEFAULT_ENABLE_OWNERS` (line 164)
- variable: `DEFAULT_EMIT_SLICES_FLAG` (line 165)
- class: `PipelineOptions` (line 171)
- class: `AnalyticsOptions` (line 185)
- class: `CLIContextState` (line 196)
- variable: `ROOT_OPTION` (line 203)
- variable: `SCIP_OPTION` (line 212)
- variable: `OUT_OPTION` (line 220)
- variable: `PYREFLY_OPTION` (line 226)
- variable: `TAGS_OPTION` (line 234)
- variable: `COVERAGE_OPTION` (line 242)
- variable: `ONLY_OPTION` (line 248)
- variable: `MAX_FILE_BYTES_OPTION` (line 253)
- variable: `OWNERS_OPTION` (line 258)
- variable: `HISTORY_WINDOW_OPTION` (line 263)
- variable: `COMMITS_WINDOW_OPTION` (line 268)
- variable: `EMIT_SLICES_OPTION` (line 273)
- variable: `SLICES_FILTER_OPTION` (line 278)
- variable: `EMIT_AST_OPTION` (line 283)
- variable: `OVERLAYS_CONFIG_OPTION` (line 288)
- variable: `OVERLAYS_SET_OPTION` (line 293)
- variable: `DRY_RUN_OPTION` (line 299)
- variable: `GLOBAL_OPTIONS_HELP` (line 306)
- variable: `app` (line 317)
- function: `_ensure_state` (line 320)
- function: `_capture_shared_state` (line 328)
- class: `OverlayCLIOptions` (line 413)
- class: `OverlayContext` (line 429)
- function: `_load_overlay_options` (line 442)
- function: `_read_overlay_config` (line 457)
- function: `_parse_bool` (line 473)
- function: `_resolve_path` (line 486)
- function: `_parse_int_option` (line 492)
- function: `_parse_path_option` (line 505)
- function: `_set_overlay_option` (line 514)
- class: `ScipContext` (line 540)
- class: `ScanInputs` (line 548)
- class: `PipelineContext` (line 561)
- class: `PipelineResult` (line 576)
- function: `_discover_py_files` (line 591)
- function: `_load_scip_artifacts` (line 615)
- function: `_collect_type_signal_map` (line 644)
- function: `_collect_coverage_map` (line 684)
- function: `_index_config_records` (line 709)
- function: `_load_tagging_rules` (line 729)
- function: `_should_skip_candidate` (line 762)
- function: `_iter_files` (line 773)
- function: `_run_pipeline` (line 785)
- function: `_execute_pipeline` (line 845)
- function: `_execute_pipeline_or_exit` (line 852)
- function: `_handle_dry_run` (line 862)
- function: `_scan_modules` (line 901)
- function: `run_all` (line 927)
- function: `run` (line 992)
- function: `scan` (line 1033)
- function: `exports` (line 1075)
- function: `graph` (line 1131)
- function: `uses` (line 1174)
- function: `typedness` (line 1217)
- function: `doc` (line 1260)
- function: `coverage` (line 1303)
- function: `config` (line 1346)
- function: `hotspots` (line 1389)
- function: `overlays` (line 1432)
- function: `to_duckdb` (line 1640)
- function: `_load_overlay_tagged_paths` (line 1665)
- function: `_build_overlay_context` (line 1702)
- function: `_build_module_row` (line 1753)
- function: `_scip_symbols_and_edges` (line 1806)
- function: `_index_module_safe` (line 1817)
- function: `_read_module_source` (line 1846)
- function: `_collect_outline_nodes` (line 1893)
- function: `_apply_index_results` (line 1925)
- function: `_outline_nodes_for` (line 1965)
- function: `_type_error_count` (line 2005)
- function: `_coverage_value` (line 2010)
- function: `_augment_module_rows` (line 2015)
- function: `_build_tag_index` (line 2087)
- function: `_infer_tags` (line 2101)
- function: `_apply_tagging` (line 2108)
- function: `_traits_from_row` (line 2129)
- function: `_build_coverage_rows` (line 2190)
- function: `_build_hotspot_rows` (line 2201)
- function: `_write_exports_outputs` (line 2215)
- function: `_write_graph_outputs` (line 2224)
- function: `_write_uses_output` (line 2231)
- function: `_apply_ownership` (line 2237)
- function: `_write_ownership_output` (line 2266)
- function: `_write_slices_output` (line 2281)
- function: `_write_typedness_output` (line 2318)
- function: `_write_doc_output` (line 2332)
- function: `_write_coverage_output` (line 2346)
- function: `_write_config_output` (line 2350)
- function: `_write_hotspot_output` (line 2354)
- function: `_write_ast_outputs` (line 2358)
- function: `_write_modules_json` (line 2377)
- function: `_write_markdown_modules` (line 2386)
- function: `_write_repo_map` (line 2400)
- function: `_write_symbol_graph` (line 2425)
- function: `_write_tabular_records` (line 2432)
- function: `_collect_ast_artifacts` (line 2437)
- function: `_write_ast_jsonl` (line 2460)
- function: `_normalize_type_signal_map` (line 2465)
- function: `_normalize_metric_map` (line 2481)
- function: `_normalize_path_key` (line 2499)
- function: `_group_configs_by_dir` (line 2503)
- function: `_config_refs_for_row` (line 2514)
- function: `_ancestor_dirs` (line 2530)
- function: `_dir_key_from_path` (line 2545)
- function: `_should_mark_overlay` (line 2552)
- function: `_ensure_package_overlays` (line 2582)
- function: `_normalized_rel_path` (line 2668)
- function: `_write_tag_index` (line 2672)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 22
- **cycle_group**: 90

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 27
- recent churn 90: 27

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

- score: 3.44

## Side Effects

- filesystem

## Complexity

- branches: 234
- cyclomatic: 235
- loc: 2689

## Doc Coverage

- `_yaml_errors` (function): summary=yes, params=ok, examples=no — Return YAML loader exceptions supported in this environment.
- `_format_stage_meta` (function): summary=no, examples=no
- `_stage_span` (function): summary=yes, params=mismatch, examples=no — Context manager logging structured stage timings.
- `_YamlDumpFn` (class): summary=no, examples=no
- `PipelineOptions` (class): summary=yes, examples=no — Resolved paths and filters required for pipeline execution.
- `AnalyticsOptions` (class): summary=yes, examples=no — Optional analytics toggles shared across commands.
- `CLIContextState` (class): summary=yes, examples=no — CLI-scoped state shared between commands.
- `_ensure_state` (function): summary=no, examples=no
- `_capture_shared_state` (function): summary=yes, params=ok, examples=no — Persist shared pipeline + analytics options on the Typer context.
- `OverlayCLIOptions` (class): summary=yes, examples=no — Mutable overlay generation options parsed from CLI/config.

## Tags

low-coverage
