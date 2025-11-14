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
- variable: `LOGGER` (line 78)
- function: `_format_stage_meta` (line 81)
- function: `_stage_span` (line 87)
- class: `_YamlDumpFn` (line 128)
- variable: `EXPORT_HUB_THRESHOLD` (line 132)
- variable: `OVERLAY_PARAM_THRESHOLD` (line 133)
- variable: `OVERLAY_FAN_IN_THRESHOLD` (line 134)
- variable: `OVERLAY_ERROR_THRESHOLD` (line 135)
- variable: `DEFAULT_MIN_ERRORS` (line 137)
- variable: `DEFAULT_MAX_OVERLAYS` (line 138)
- variable: `DEFAULT_INCLUDE_PUBLIC_DEFS` (line 139)
- variable: `DEFAULT_INJECT_GETATTR_ANY` (line 140)
- variable: `DEFAULT_DRY_RUN` (line 141)
- variable: `DEFAULT_ACTIVATE` (line 142)
- variable: `DEFAULT_DEACTIVATE` (line 143)
- variable: `DEFAULT_USE_TYPE_ERROR_OVERLAYS` (line 144)
- variable: `DEFAULT_EMIT_AST` (line 145)
- variable: `DEFAULT_MAX_FILE_BYTES` (line 146)
- variable: `DEFAULT_OWNER_HISTORY_DAYS` (line 147)
- variable: `DEFAULT_COMMITS_WINDOW` (line 148)
- variable: `DEFAULT_ENABLE_OWNERS` (line 149)
- variable: `DEFAULT_EMIT_SLICES_FLAG` (line 150)
- class: `PipelineOptions` (line 156)
- class: `AnalyticsOptions` (line 170)
- class: `CLIContextState` (line 181)
- variable: `ROOT_OPTION` (line 188)
- variable: `SCIP_OPTION` (line 197)
- variable: `OUT_OPTION` (line 205)
- variable: `PYREFLY_OPTION` (line 211)
- variable: `TAGS_OPTION` (line 219)
- variable: `COVERAGE_OPTION` (line 227)
- variable: `ONLY_OPTION` (line 233)
- variable: `MAX_FILE_BYTES_OPTION` (line 238)
- variable: `OWNERS_OPTION` (line 243)
- variable: `HISTORY_WINDOW_OPTION` (line 248)
- variable: `COMMITS_WINDOW_OPTION` (line 253)
- variable: `EMIT_SLICES_OPTION` (line 258)
- variable: `SLICES_FILTER_OPTION` (line 263)
- variable: `EMIT_AST_OPTION` (line 268)
- variable: `OVERLAYS_CONFIG_OPTION` (line 273)
- variable: `OVERLAYS_SET_OPTION` (line 278)
- variable: `DRY_RUN_OPTION` (line 284)
- variable: `GLOBAL_OPTIONS_HELP` (line 291)
- variable: `app` (line 302)
- function: `_ensure_state` (line 305)
- function: `_capture_shared_state` (line 313)
- class: `OverlayCLIOptions` (line 398)
- class: `OverlayContext` (line 414)
- function: `_load_overlay_options` (line 427)
- function: `_read_overlay_config` (line 442)
- function: `_parse_bool` (line 458)
- function: `_resolve_path` (line 471)
- function: `_parse_int_option` (line 477)
- function: `_parse_path_option` (line 490)
- function: `_set_overlay_option` (line 499)
- class: `ScipContext` (line 525)
- class: `ScanInputs` (line 533)
- class: `PipelineContext` (line 546)
- class: `PipelineResult` (line 561)
- function: `_discover_py_files` (line 576)
- function: `_load_scip_artifacts` (line 600)
- function: `_collect_type_signal_map` (line 629)
- function: `_collect_coverage_map` (line 669)
- function: `_index_config_records` (line 694)
- function: `_load_tagging_rules` (line 714)
- function: `_should_skip_candidate` (line 747)
- function: `_iter_files` (line 758)
- function: `_run_pipeline` (line 770)
- function: `_execute_pipeline` (line 830)
- function: `_execute_pipeline_or_exit` (line 837)
- function: `_handle_dry_run` (line 847)
- function: `_scan_modules` (line 881)
- function: `run_all` (line 907)
- function: `run` (line 972)
- function: `scan` (line 1013)
- function: `exports` (line 1055)
- function: `graph` (line 1111)
- function: `uses` (line 1154)
- function: `typedness` (line 1197)
- function: `doc` (line 1240)
- function: `coverage` (line 1283)
- function: `config` (line 1326)
- function: `hotspots` (line 1369)
- function: `overlays` (line 1412)
- function: `to_duckdb` (line 1620)
- function: `_load_overlay_tagged_paths` (line 1645)
- function: `_build_overlay_context` (line 1682)
- function: `_build_module_row` (line 1733)
- function: `_scip_symbols_and_edges` (line 1786)
- function: `_index_module_safe` (line 1797)
- function: `_read_module_source` (line 1826)
- function: `_collect_outline_nodes` (line 1873)
- function: `_apply_index_results` (line 1905)
- function: `_outline_nodes_for` (line 1945)
- function: `_type_error_count` (line 1985)
- function: `_coverage_value` (line 1990)
- function: `_augment_module_rows` (line 1995)
- function: `_build_tag_index` (line 2067)
- function: `_infer_tags` (line 2081)
- function: `_apply_tagging` (line 2088)
- function: `_traits_from_row` (line 2109)
- function: `_build_coverage_rows` (line 2170)
- function: `_build_hotspot_rows` (line 2181)
- function: `_write_exports_outputs` (line 2195)
- function: `_write_graph_outputs` (line 2204)
- function: `_write_uses_output` (line 2211)
- function: `_apply_ownership` (line 2217)
- function: `_write_ownership_output` (line 2246)
- function: `_write_slices_output` (line 2261)
- function: `_write_typedness_output` (line 2298)
- function: `_write_doc_output` (line 2312)
- function: `_write_coverage_output` (line 2326)
- function: `_write_config_output` (line 2330)
- function: `_write_hotspot_output` (line 2334)
- function: `_write_ast_outputs` (line 2338)
- function: `_write_modules_json` (line 2357)
- function: `_write_markdown_modules` (line 2366)
- function: `_write_repo_map` (line 2380)
- function: `_write_symbol_graph` (line 2405)
- function: `_write_tabular_records` (line 2412)
- function: `_collect_ast_artifacts` (line 2417)
- function: `_write_ast_jsonl` (line 2440)
- function: `_normalize_type_signal_map` (line 2445)
- function: `_normalize_metric_map` (line 2461)
- function: `_normalize_path_key` (line 2479)
- function: `_group_configs_by_dir` (line 2483)
- function: `_config_refs_for_row` (line 2494)
- function: `_ancestor_dirs` (line 2510)
- function: `_dir_key_from_path` (line 2525)
- function: `_should_mark_overlay` (line 2532)
- function: `_ensure_package_overlays` (line 2562)
- function: `_normalized_rel_path` (line 2648)
- function: `_write_tag_index` (line 2652)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 22
- **cycle_group**: 104

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 24
- recent churn 90: 24

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

- branches: 233
- cyclomatic: 234
- loc: 2669

## Doc Coverage

- `_format_stage_meta` (function): summary=no, examples=no
- `_stage_span` (function): summary=yes, params=mismatch, examples=no — Context manager logging structured stage timings.
- `_YamlDumpFn` (class): summary=no, examples=no
- `PipelineOptions` (class): summary=yes, examples=no — Resolved paths and filters required for pipeline execution.
- `AnalyticsOptions` (class): summary=yes, examples=no — Optional analytics toggles shared across commands.
- `CLIContextState` (class): summary=yes, examples=no — CLI-scoped state shared between commands.
- `_ensure_state` (function): summary=no, examples=no
- `_capture_shared_state` (function): summary=yes, params=ok, examples=no — Persist shared pipeline + analytics options on the Typer context.
- `OverlayCLIOptions` (class): summary=yes, examples=no — Mutable overlay generation options parsed from CLI/config.
- `OverlayContext` (class): summary=yes, examples=no — Aggregated context used during overlay generation.

## Tags

low-coverage
