# cli/enrich_pipeline.py

## Docstring

```
CLI entrypoint for repo enrichment and targeted overlay generation.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import ast
- from **(absolute)** import json
- from **(absolute)** import logging
- from **(absolute)** import sys
- from **(absolute)** import time
- from **collections.abc** import Callable, Iterable, Iterator, Mapping, Sequence
- from **contextlib** import contextmanager
- from **dataclasses** import asdict, dataclass, field
- from **datetime** import UTC, datetime
- from **fnmatch** import fnmatch
- from **pathlib** import Path
- from **typing** import Annotated, Any, Protocol, TypedDict, Unpack, cast
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
- from **codeintel_rev.enrich.stubs_overlay** import OverlayInputs, OverlayPolicy, generate_overlay_for_file
- from **codeintel_rev.enrich.tagging** import ModuleTraits, infer_tags, load_rules
- from **codeintel_rev.enrich.tree_sitter_bridge** import build_outline
- from **codeintel_rev.enrich.validators** import ModuleRecordModel
- from **codeintel_rev.export_resolver** import build_module_name_map, resolve_exports
- from **codeintel_rev.risk_hotspots** import compute_hotspot_score
- from **codeintel_rev.typedness** import FileTypeSignals, collect_type_signals
- from **codeintel_rev.uses_builder** import UseGraph, build_use_graph, write_use_graph
- from **(absolute)** import yaml

## Definitions

- variable: `yaml_module` (line 74)
- function: `_yaml_errors` (line 77)
- variable: `YAML_ERRORS` (line 90)
- variable: `LOGGER` (line 93)
- function: `_attach_argv_normalizer` (line 96)
- function: `_format_stage_meta` (line 104)
- function: `_stage_span` (line 110)
- class: `StageMeta` (line 162)
- function: `_stage` (line 170)
- class: `_YamlDumpKwargs` (line 201)
- class: `_YamlDumpFn` (line 205)
- variable: `EXPORT_HUB_THRESHOLD` (line 213)
- variable: `OVERLAY_PARAM_THRESHOLD` (line 214)
- variable: `OVERLAY_FAN_IN_THRESHOLD` (line 215)
- variable: `OVERLAY_ERROR_THRESHOLD` (line 216)
- variable: `DEFAULT_MIN_ERRORS` (line 218)
- variable: `DEFAULT_MAX_OVERLAYS` (line 219)
- variable: `DEFAULT_INCLUDE_PUBLIC_DEFS` (line 220)
- variable: `DEFAULT_INJECT_GETATTR_ANY` (line 221)
- variable: `DEFAULT_DRY_RUN` (line 222)
- variable: `DEFAULT_ACTIVATE` (line 223)
- variable: `DEFAULT_DEACTIVATE` (line 224)
- variable: `DEFAULT_USE_TYPE_ERROR_OVERLAYS` (line 225)
- variable: `DEFAULT_EMIT_AST` (line 226)
- variable: `DEFAULT_MAX_FILE_BYTES` (line 227)
- variable: `DEFAULT_OWNER_HISTORY_DAYS` (line 228)
- variable: `DEFAULT_COMMITS_WINDOW` (line 229)
- variable: `DEFAULT_ENABLE_OWNERS` (line 230)
- variable: `DEFAULT_EMIT_SLICES_FLAG` (line 231)
- class: `PipelineOptions` (line 237)
- class: `AnalyticsOptions` (line 251)
- class: `CLIContextState` (line 262)
- variable: `ROOT_OPTION` (line 269)
- variable: `SCIP_OPTION` (line 278)
- variable: `OUT_OPTION` (line 286)
- variable: `PYREFLY_OPTION` (line 292)
- variable: `TAGS_OPTION` (line 300)
- variable: `COVERAGE_OPTION` (line 308)
- variable: `ONLY_OPTION` (line 314)
- variable: `MAX_FILE_BYTES_OPTION` (line 319)
- variable: `OWNERS_OPTION` (line 324)
- variable: `HISTORY_WINDOW_OPTION` (line 329)
- variable: `COMMITS_WINDOW_OPTION` (line 334)
- variable: `EMIT_SLICES_OPTION` (line 339)
- variable: `SLICES_FILTER_OPTION` (line 344)
- variable: `EMIT_AST_OPTION` (line 349)
- variable: `OVERLAYS_CONFIG_OPTION` (line 354)
- variable: `OVERLAYS_SET_OPTION` (line 359)
- variable: `DRY_RUN_OPTION` (line 365)
- variable: `GLOBAL_OPTIONS_HELP` (line 372)
- function: `normalize_global_cli_args` (line 405)
- variable: `app` (line 449)
- function: `shared_options` (line 454)
- function: `_ensure_state` (line 492)
- class: `OverlayCLIOptions` (line 501)
- class: `OverlayContext` (line 517)
- function: `_load_overlay_options` (line 530)
- function: `_read_overlay_config` (line 545)
- function: `_parse_bool` (line 561)
- function: `_resolve_path` (line 574)
- function: `_parse_int_option` (line 580)
- function: `_parse_path_option` (line 593)
- function: `_set_overlay_option` (line 602)
- class: `ScipContext` (line 628)
- class: `ScanInputs` (line 636)
- class: `PipelineContext` (line 649)
- class: `PipelineResult` (line 664)
- class: `PreparedPipeline` (line 680)
- class: `AnalyticsArtifacts` (line 688)
- class: `ConfigReferenceState` (line 700)
- function: `_discover_py_files` (line 708)
- function: `_load_scip_artifacts` (line 732)
- function: `_collect_type_signal_map` (line 761)
- function: `_collect_coverage_map` (line 801)
- function: `_index_config_records` (line 828)
- function: `_load_tagging_rules` (line 848)
- function: `_should_skip_candidate` (line 881)
- function: `_iter_files` (line 892)
- function: `_prepare_pipeline` (line 904)
- function: `_compute_pipeline_analytics` (line 933)
- function: `_run_pipeline` (line 961)
- function: `_execute_pipeline` (line 980)
- function: `_execute_pipeline_or_exit` (line 987)
- function: `_handle_dry_run` (line 997)
- function: `_scan_modules` (line 1036)
- function: `run_all` (line 1062)
- function: `run` (line 1098)
- function: `scan` (line 1109)
- function: `exports` (line 1121)
- function: `to_duckdb` (line 1148)
- function: `_load_overlay_tagged_paths` (line 1173)
- function: `_build_overlay_context` (line 1210)
- function: `_build_module_row` (line 1261)
- function: `_scip_symbols_and_edges` (line 1314)
- function: `_index_module_safe` (line 1325)
- function: `_read_module_source` (line 1354)
- function: `_collect_outline_nodes` (line 1401)
- function: `_apply_index_results` (line 1433)
- function: `_outline_nodes_for` (line 1473)
- function: `_type_error_count` (line 1513)
- function: `_coverage_value` (line 1518)
- function: `_prepare_config_state` (line 1523)
- function: `_augment_module_rows` (line 1534)
- function: `_build_tag_index` (line 1604)
- function: `_infer_tags` (line 1618)
- function: `_apply_tagging` (line 1625)
- function: `_traits_from_row` (line 1646)
- function: `_build_coverage_rows` (line 1707)
- function: `_build_hotspot_rows` (line 1718)
- function: `_write_exports_outputs` (line 1732)
- function: `_write_graph_outputs` (line 1741)
- function: `_write_uses_output` (line 1748)
- function: `_apply_ownership` (line 1754)
- function: `_write_ownership_output` (line 1783)
- function: `_write_slices_output` (line 1798)
- function: `_write_typedness_output` (line 1835)
- function: `_write_doc_output` (line 1849)
- function: `_write_coverage_output` (line 1863)
- function: `_write_config_output` (line 1867)
- function: `_write_hotspot_output` (line 1871)
- function: `_write_ast_outputs` (line 1875)
- function: `_write_modules_json` (line 1894)
- function: `_write_markdown_modules` (line 1903)
- function: `_write_repo_map` (line 1917)
- function: `_write_symbol_graph` (line 1942)
- function: `_write_tabular_records` (line 1949)
- function: `_collect_ast_artifacts` (line 1954)
- function: `_write_ast_jsonl` (line 1977)
- function: `_normalize_type_signal_map` (line 1982)
- function: `_normalize_metric_map` (line 1998)
- function: `_normalize_path_key` (line 2016)
- function: `_group_configs_by_dir` (line 2020)
- function: `_config_refs_for_row` (line 2031)
- function: `_ancestor_dirs` (line 2047)
- function: `_dir_key_from_path` (line 2062)
- function: `_should_mark_overlay` (line 2069)
- function: `_ensure_package_overlays` (line 2099)
- function: `_normalized_rel_path` (line 2185)
- function: `_write_tag_index` (line 2189)
- variable: `attach_argv_normalizer` (line 2205)
- variable: `execute_pipeline_or_exit` (line 2206)
- variable: `handle_dry_run` (line 2207)
- variable: `write_graph_outputs` (line 2208)
- variable: `write_uses_output` (line 2209)
- variable: `write_typedness_output` (line 2210)
- variable: `write_doc_output` (line 2211)
- variable: `write_coverage_output` (line 2212)
- variable: `write_config_output` (line 2213)
- variable: `write_hotspot_output` (line 2214)
- variable: `ensure_state` (line 2215)
- variable: `load_overlay_options` (line 2216)
- variable: `build_overlay_context` (line 2217)
- variable: `iter_files` (line 2218)
- variable: `normalized_rel_path` (line 2219)
- variable: `ensure_package_overlays` (line 2220)
- variable: `build_module_row` (line 2221)
- variable: `outline_nodes_for` (line 2222)
- variable: `type_error_count` (line 2223)
- variable: `apply_tagging` (line 2224)
- function: `main` (line 2227)

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 22
- **cycle_group**: 81

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 1
- recent churn 90: 1

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

- score: 3.47

## Side Effects

- filesystem

## Complexity

- branches: 219
- cyclomatic: 220
- loc: 2235

## Doc Coverage

- `_yaml_errors` (function): summary=yes, params=ok, examples=no — Return YAML loader exceptions supported in this environment.
- `_attach_argv_normalizer` (function): summary=yes, params=mismatch, examples=no — Attach argv normalizer metadata for CLI tests.
- `_format_stage_meta` (function): summary=no, examples=no
- `_stage_span` (function): summary=yes, params=mismatch, examples=no — Context manager logging structured stage timings.
- `StageMeta` (class): summary=yes, examples=no — Structured metadata describing a stage run.
- `_stage` (function): summary=yes, params=ok, examples=no — Run a stage using the shared span helper.
- `_YamlDumpKwargs` (class): summary=no, examples=no
- `_YamlDumpFn` (class): summary=no, examples=no
- `PipelineOptions` (class): summary=yes, examples=no — Resolved paths and filters required for pipeline execution.
- `AnalyticsOptions` (class): summary=yes, examples=no — Optional analytics toggles shared across commands.

## Tags

low-coverage
