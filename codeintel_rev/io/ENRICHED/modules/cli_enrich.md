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
- from **(absolute)** import sys
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

- variable: `yaml_module` (line 76)
- function: `_yaml_errors` (line 79)
- variable: `YAML_ERRORS` (line 92)
- variable: `LOGGER` (line 95)
- function: `_format_stage_meta` (line 98)
- function: `_stage_span` (line 104)
- class: `StageMeta` (line 156)
- function: `_stage` (line 164)
- class: `_YamlDumpFn` (line 195)
- variable: `EXPORT_HUB_THRESHOLD` (line 199)
- variable: `OVERLAY_PARAM_THRESHOLD` (line 200)
- variable: `OVERLAY_FAN_IN_THRESHOLD` (line 201)
- variable: `OVERLAY_ERROR_THRESHOLD` (line 202)
- variable: `DEFAULT_MIN_ERRORS` (line 204)
- variable: `DEFAULT_MAX_OVERLAYS` (line 205)
- variable: `DEFAULT_INCLUDE_PUBLIC_DEFS` (line 206)
- variable: `DEFAULT_INJECT_GETATTR_ANY` (line 207)
- variable: `DEFAULT_DRY_RUN` (line 208)
- variable: `DEFAULT_ACTIVATE` (line 209)
- variable: `DEFAULT_DEACTIVATE` (line 210)
- variable: `DEFAULT_USE_TYPE_ERROR_OVERLAYS` (line 211)
- variable: `DEFAULT_EMIT_AST` (line 212)
- variable: `DEFAULT_MAX_FILE_BYTES` (line 213)
- variable: `DEFAULT_OWNER_HISTORY_DAYS` (line 214)
- variable: `DEFAULT_COMMITS_WINDOW` (line 215)
- variable: `DEFAULT_ENABLE_OWNERS` (line 216)
- variable: `DEFAULT_EMIT_SLICES_FLAG` (line 217)
- class: `PipelineOptions` (line 223)
- class: `AnalyticsOptions` (line 237)
- class: `CLIContextState` (line 248)
- variable: `ROOT_OPTION` (line 255)
- variable: `SCIP_OPTION` (line 264)
- variable: `OUT_OPTION` (line 272)
- variable: `PYREFLY_OPTION` (line 278)
- variable: `TAGS_OPTION` (line 286)
- variable: `COVERAGE_OPTION` (line 294)
- variable: `ONLY_OPTION` (line 300)
- variable: `MAX_FILE_BYTES_OPTION` (line 305)
- variable: `OWNERS_OPTION` (line 310)
- variable: `HISTORY_WINDOW_OPTION` (line 315)
- variable: `COMMITS_WINDOW_OPTION` (line 320)
- variable: `EMIT_SLICES_OPTION` (line 325)
- variable: `SLICES_FILTER_OPTION` (line 330)
- variable: `EMIT_AST_OPTION` (line 335)
- variable: `OVERLAYS_CONFIG_OPTION` (line 340)
- variable: `OVERLAYS_SET_OPTION` (line 345)
- variable: `DRY_RUN_OPTION` (line 351)
- variable: `GLOBAL_OPTIONS_HELP` (line 358)
- function: `normalize_global_cli_args` (line 391)
- variable: `app` (line 435)
- function: `shared_options` (line 440)
- function: `_ensure_state` (line 478)
- class: `OverlayCLIOptions` (line 487)
- class: `OverlayContext` (line 503)
- function: `_load_overlay_options` (line 516)
- function: `_read_overlay_config` (line 531)
- function: `_parse_bool` (line 547)
- function: `_resolve_path` (line 560)
- function: `_parse_int_option` (line 566)
- function: `_parse_path_option` (line 579)
- function: `_set_overlay_option` (line 588)
- class: `ScipContext` (line 614)
- class: `ScanInputs` (line 622)
- class: `PipelineContext` (line 635)
- class: `PipelineResult` (line 650)
- class: `PreparedPipeline` (line 666)
- class: `AnalyticsArtifacts` (line 674)
- class: `ConfigReferenceState` (line 686)
- function: `_discover_py_files` (line 694)
- function: `_load_scip_artifacts` (line 718)
- function: `_collect_type_signal_map` (line 747)
- function: `_collect_coverage_map` (line 787)
- function: `_index_config_records` (line 814)
- function: `_load_tagging_rules` (line 834)
- function: `_should_skip_candidate` (line 867)
- function: `_iter_files` (line 878)
- function: `_prepare_pipeline` (line 890)
- function: `_compute_pipeline_analytics` (line 919)
- function: `_run_pipeline` (line 947)
- function: `_execute_pipeline` (line 966)
- function: `_execute_pipeline_or_exit` (line 973)
- function: `_handle_dry_run` (line 983)
- function: `_scan_modules` (line 1022)
- function: `run_all` (line 1048)
- function: `run` (line 1084)
- function: `scan` (line 1095)
- function: `exports` (line 1107)
- function: `graph` (line 1134)
- function: `uses` (line 1148)
- function: `typedness` (line 1162)
- function: `doc` (line 1176)
- function: `coverage` (line 1190)
- function: `config` (line 1204)
- function: `hotspots` (line 1218)
- function: `overlays` (line 1232)
- function: `to_duckdb` (line 1369)
- function: `_load_overlay_tagged_paths` (line 1394)
- function: `_build_overlay_context` (line 1431)
- function: `_build_module_row` (line 1482)
- function: `_scip_symbols_and_edges` (line 1535)
- function: `_index_module_safe` (line 1546)
- function: `_read_module_source` (line 1575)
- function: `_collect_outline_nodes` (line 1622)
- function: `_apply_index_results` (line 1654)
- function: `_outline_nodes_for` (line 1694)
- function: `_type_error_count` (line 1734)
- function: `_coverage_value` (line 1739)
- function: `_prepare_config_state` (line 1744)
- function: `_augment_module_rows` (line 1755)
- function: `_build_tag_index` (line 1825)
- function: `_infer_tags` (line 1839)
- function: `_apply_tagging` (line 1846)
- function: `_traits_from_row` (line 1867)
- function: `_build_coverage_rows` (line 1928)
- function: `_build_hotspot_rows` (line 1939)
- function: `_write_exports_outputs` (line 1953)
- function: `_write_graph_outputs` (line 1962)
- function: `_write_uses_output` (line 1969)
- function: `_apply_ownership` (line 1975)
- function: `_write_ownership_output` (line 2004)
- function: `_write_slices_output` (line 2019)
- function: `_write_typedness_output` (line 2056)
- function: `_write_doc_output` (line 2070)
- function: `_write_coverage_output` (line 2084)
- function: `_write_config_output` (line 2088)
- function: `_write_hotspot_output` (line 2092)
- function: `_write_ast_outputs` (line 2096)
- function: `_write_modules_json` (line 2115)
- function: `_write_markdown_modules` (line 2124)
- function: `_write_repo_map` (line 2138)
- function: `_write_symbol_graph` (line 2163)
- function: `_write_tabular_records` (line 2170)
- function: `_collect_ast_artifacts` (line 2175)
- function: `_write_ast_jsonl` (line 2198)
- function: `_normalize_type_signal_map` (line 2203)
- function: `_normalize_metric_map` (line 2219)
- function: `_normalize_path_key` (line 2237)
- function: `_group_configs_by_dir` (line 2241)
- function: `_config_refs_for_row` (line 2252)
- function: `_ancestor_dirs` (line 2268)
- function: `_dir_key_from_path` (line 2283)
- function: `_should_mark_overlay` (line 2290)
- function: `_ensure_package_overlays` (line 2320)
- function: `_normalized_rel_path` (line 2406)
- function: `_write_tag_index` (line 2410)
- function: `main` (line 2425)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 22
- **cycle_group**: 90

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 30
- recent churn 90: 30

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

- score: 3.45

## Side Effects

- filesystem

## Complexity

- branches: 241
- cyclomatic: 242
- loc: 2433

## Doc Coverage

- `_yaml_errors` (function): summary=yes, params=ok, examples=no — Return YAML loader exceptions supported in this environment.
- `_format_stage_meta` (function): summary=no, examples=no
- `_stage_span` (function): summary=yes, params=mismatch, examples=no — Context manager logging structured stage timings.
- `StageMeta` (class): summary=yes, examples=no — Structured metadata describing a stage run.
- `_stage` (function): summary=yes, params=ok, examples=no — Run a stage using the shared span helper.
- `_YamlDumpFn` (class): summary=no, examples=no
- `PipelineOptions` (class): summary=yes, examples=no — Resolved paths and filters required for pipeline execution.
- `AnalyticsOptions` (class): summary=yes, examples=no — Optional analytics toggles shared across commands.
- `CLIContextState` (class): summary=yes, examples=no — CLI-scoped state shared between commands.
- `normalize_global_cli_args` (function): summary=yes, params=ok, examples=no — Return arguments with known global options positioned before the command.

## Tags

low-coverage
