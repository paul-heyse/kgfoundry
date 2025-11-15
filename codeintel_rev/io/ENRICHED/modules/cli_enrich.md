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
- class: `_YamlDumpFn` (line 139)
- variable: `EXPORT_HUB_THRESHOLD` (line 143)
- variable: `OVERLAY_PARAM_THRESHOLD` (line 144)
- variable: `OVERLAY_FAN_IN_THRESHOLD` (line 145)
- variable: `OVERLAY_ERROR_THRESHOLD` (line 146)
- variable: `DEFAULT_MIN_ERRORS` (line 148)
- variable: `DEFAULT_MAX_OVERLAYS` (line 149)
- variable: `DEFAULT_INCLUDE_PUBLIC_DEFS` (line 150)
- variable: `DEFAULT_INJECT_GETATTR_ANY` (line 151)
- variable: `DEFAULT_DRY_RUN` (line 152)
- variable: `DEFAULT_ACTIVATE` (line 153)
- variable: `DEFAULT_DEACTIVATE` (line 154)
- variable: `DEFAULT_USE_TYPE_ERROR_OVERLAYS` (line 155)
- variable: `DEFAULT_EMIT_AST` (line 156)
- variable: `DEFAULT_MAX_FILE_BYTES` (line 157)
- variable: `DEFAULT_OWNER_HISTORY_DAYS` (line 158)
- variable: `DEFAULT_COMMITS_WINDOW` (line 159)
- variable: `DEFAULT_ENABLE_OWNERS` (line 160)
- variable: `DEFAULT_EMIT_SLICES_FLAG` (line 161)
- class: `PipelineOptions` (line 167)
- class: `AnalyticsOptions` (line 181)
- class: `CLIContextState` (line 192)
- variable: `ROOT_OPTION` (line 199)
- variable: `SCIP_OPTION` (line 208)
- variable: `OUT_OPTION` (line 216)
- variable: `PYREFLY_OPTION` (line 222)
- variable: `TAGS_OPTION` (line 230)
- variable: `COVERAGE_OPTION` (line 238)
- variable: `ONLY_OPTION` (line 244)
- variable: `MAX_FILE_BYTES_OPTION` (line 249)
- variable: `OWNERS_OPTION` (line 254)
- variable: `HISTORY_WINDOW_OPTION` (line 259)
- variable: `COMMITS_WINDOW_OPTION` (line 264)
- variable: `EMIT_SLICES_OPTION` (line 269)
- variable: `SLICES_FILTER_OPTION` (line 274)
- variable: `EMIT_AST_OPTION` (line 279)
- variable: `OVERLAYS_CONFIG_OPTION` (line 284)
- variable: `OVERLAYS_SET_OPTION` (line 289)
- variable: `DRY_RUN_OPTION` (line 295)
- variable: `GLOBAL_OPTIONS_HELP` (line 302)
- variable: `app` (line 313)
- function: `_ensure_state` (line 316)
- function: `_capture_shared_state` (line 324)
- class: `OverlayCLIOptions` (line 409)
- class: `OverlayContext` (line 425)
- function: `_load_overlay_options` (line 438)
- function: `_read_overlay_config` (line 453)
- function: `_parse_bool` (line 469)
- function: `_resolve_path` (line 482)
- function: `_parse_int_option` (line 488)
- function: `_parse_path_option` (line 501)
- function: `_set_overlay_option` (line 510)
- class: `ScipContext` (line 536)
- class: `ScanInputs` (line 544)
- class: `PipelineContext` (line 557)
- class: `PipelineResult` (line 572)
- function: `_discover_py_files` (line 587)
- function: `_load_scip_artifacts` (line 611)
- function: `_collect_type_signal_map` (line 640)
- function: `_collect_coverage_map` (line 680)
- function: `_index_config_records` (line 705)
- function: `_load_tagging_rules` (line 725)
- function: `_should_skip_candidate` (line 758)
- function: `_iter_files` (line 769)
- function: `_run_pipeline` (line 781)
- function: `_execute_pipeline` (line 841)
- function: `_execute_pipeline_or_exit` (line 848)
- function: `_handle_dry_run` (line 858)
- function: `_scan_modules` (line 897)
- function: `run_all` (line 923)
- function: `run` (line 988)
- function: `scan` (line 1029)
- function: `exports` (line 1071)
- function: `graph` (line 1127)
- function: `uses` (line 1170)
- function: `typedness` (line 1213)
- function: `doc` (line 1256)
- function: `coverage` (line 1299)
- function: `config` (line 1342)
- function: `hotspots` (line 1385)
- function: `overlays` (line 1428)
- function: `to_duckdb` (line 1636)
- function: `_load_overlay_tagged_paths` (line 1661)
- function: `_build_overlay_context` (line 1698)
- function: `_build_module_row` (line 1749)
- function: `_scip_symbols_and_edges` (line 1802)
- function: `_index_module_safe` (line 1813)
- function: `_read_module_source` (line 1842)
- function: `_collect_outline_nodes` (line 1889)
- function: `_apply_index_results` (line 1921)
- function: `_outline_nodes_for` (line 1961)
- function: `_type_error_count` (line 2001)
- function: `_coverage_value` (line 2006)
- function: `_augment_module_rows` (line 2011)
- function: `_build_tag_index` (line 2083)
- function: `_infer_tags` (line 2097)
- function: `_apply_tagging` (line 2104)
- function: `_traits_from_row` (line 2125)
- function: `_build_coverage_rows` (line 2186)
- function: `_build_hotspot_rows` (line 2197)
- function: `_write_exports_outputs` (line 2211)
- function: `_write_graph_outputs` (line 2220)
- function: `_write_uses_output` (line 2227)
- function: `_apply_ownership` (line 2233)
- function: `_write_ownership_output` (line 2262)
- function: `_write_slices_output` (line 2277)
- function: `_write_typedness_output` (line 2314)
- function: `_write_doc_output` (line 2328)
- function: `_write_coverage_output` (line 2342)
- function: `_write_config_output` (line 2346)
- function: `_write_hotspot_output` (line 2350)
- function: `_write_ast_outputs` (line 2354)
- function: `_write_modules_json` (line 2373)
- function: `_write_markdown_modules` (line 2382)
- function: `_write_repo_map` (line 2396)
- function: `_write_symbol_graph` (line 2421)
- function: `_write_tabular_records` (line 2428)
- function: `_collect_ast_artifacts` (line 2433)
- function: `_write_ast_jsonl` (line 2456)
- function: `_normalize_type_signal_map` (line 2461)
- function: `_normalize_metric_map` (line 2477)
- function: `_normalize_path_key` (line 2495)
- function: `_group_configs_by_dir` (line 2499)
- function: `_config_refs_for_row` (line 2510)
- function: `_ancestor_dirs` (line 2526)
- function: `_dir_key_from_path` (line 2541)
- function: `_should_mark_overlay` (line 2548)
- function: `_ensure_package_overlays` (line 2578)
- function: `_normalized_rel_path` (line 2664)
- function: `_write_tag_index` (line 2668)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 22
- **cycle_group**: 111

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 26
- recent churn 90: 26

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
- loc: 2685

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
