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
- from **collections.abc** import Callable, Iterable, Iterator, Mapping, Sequence
- from **contextlib** import contextmanager
- from **dataclasses** import asdict, dataclass, field, replace
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
- function: `_attach_argv_normalizer` (line 98)
- function: `_format_stage_meta` (line 106)
- function: `_stage_span` (line 112)
- class: `StageMeta` (line 164)
- function: `_stage` (line 172)
- class: `_YamlDumpKwargs` (line 203)
- class: `_YamlDumpFn` (line 207)
- variable: `EXPORT_HUB_THRESHOLD` (line 215)
- variable: `OVERLAY_PARAM_THRESHOLD` (line 216)
- variable: `OVERLAY_FAN_IN_THRESHOLD` (line 217)
- variable: `OVERLAY_ERROR_THRESHOLD` (line 218)
- variable: `DEFAULT_MIN_ERRORS` (line 220)
- variable: `DEFAULT_MAX_OVERLAYS` (line 221)
- variable: `DEFAULT_INCLUDE_PUBLIC_DEFS` (line 222)
- variable: `DEFAULT_INJECT_GETATTR_ANY` (line 223)
- variable: `DEFAULT_DRY_RUN` (line 224)
- variable: `DEFAULT_ACTIVATE` (line 225)
- variable: `DEFAULT_DEACTIVATE` (line 226)
- variable: `DEFAULT_USE_TYPE_ERROR_OVERLAYS` (line 227)
- variable: `DEFAULT_EMIT_AST` (line 228)
- variable: `DEFAULT_MAX_FILE_BYTES` (line 229)
- variable: `DEFAULT_OWNER_HISTORY_DAYS` (line 230)
- variable: `DEFAULT_COMMITS_WINDOW` (line 231)
- variable: `DEFAULT_ENABLE_OWNERS` (line 232)
- variable: `DEFAULT_EMIT_SLICES_FLAG` (line 233)
- class: `PipelineOptions` (line 239)
- class: `AnalyticsOptions` (line 253)
- class: `CLIContextState` (line 264)
- variable: `ROOT_OPTION` (line 271)
- variable: `SCIP_OPTION` (line 280)
- variable: `OUT_OPTION` (line 288)
- variable: `PYREFLY_OPTION` (line 294)
- variable: `TAGS_OPTION` (line 302)
- variable: `COVERAGE_OPTION` (line 310)
- variable: `ONLY_OPTION` (line 316)
- variable: `MAX_FILE_BYTES_OPTION` (line 321)
- variable: `OWNERS_OPTION` (line 326)
- variable: `HISTORY_WINDOW_OPTION` (line 331)
- variable: `COMMITS_WINDOW_OPTION` (line 336)
- variable: `EMIT_SLICES_OPTION` (line 341)
- variable: `SLICES_FILTER_OPTION` (line 346)
- variable: `EMIT_AST_OPTION` (line 351)
- variable: `OVERLAYS_CONFIG_OPTION` (line 356)
- variable: `OVERLAYS_SET_OPTION` (line 361)
- variable: `DRY_RUN_OPTION` (line 367)
- variable: `GLOBAL_OPTIONS_HELP` (line 374)
- function: `normalize_global_cli_args` (line 407)
- variable: `app` (line 451)
- function: `shared_options` (line 456)
- function: `_ensure_state` (line 494)
- class: `OverlayCLIOptions` (line 503)
- class: `OverlayContext` (line 519)
- function: `_load_overlay_options` (line 532)
- function: `_read_overlay_config` (line 547)
- function: `_parse_bool` (line 563)
- function: `_resolve_path` (line 576)
- function: `_parse_int_option` (line 582)
- function: `_parse_path_option` (line 595)
- function: `_set_overlay_option` (line 604)
- class: `ScipContext` (line 630)
- class: `ScanInputs` (line 638)
- class: `PipelineContext` (line 651)
- class: `PipelineResult` (line 666)
- class: `PreparedPipeline` (line 682)
- class: `AnalyticsArtifacts` (line 690)
- class: `ConfigReferenceState` (line 702)
- function: `_discover_py_files` (line 710)
- function: `_load_scip_artifacts` (line 734)
- function: `_collect_type_signal_map` (line 763)
- function: `_collect_coverage_map` (line 803)
- function: `_index_config_records` (line 830)
- function: `_load_tagging_rules` (line 850)
- function: `_should_skip_candidate` (line 883)
- function: `_iter_files` (line 894)
- function: `_prepare_pipeline` (line 906)
- function: `_compute_pipeline_analytics` (line 935)
- function: `_run_pipeline` (line 963)
- function: `_execute_pipeline` (line 982)
- function: `_execute_pipeline_or_exit` (line 989)
- function: `_handle_dry_run` (line 999)
- function: `_scan_modules` (line 1038)
- function: `run_all` (line 1064)
- function: `run` (line 1100)
- function: `scan` (line 1111)
- function: `exports` (line 1123)
- function: `graph` (line 1150)
- function: `uses` (line 1164)
- function: `typedness` (line 1178)
- function: `doc` (line 1192)
- function: `coverage` (line 1206)
- function: `config` (line 1220)
- function: `hotspots` (line 1234)
- function: `overlays` (line 1248)
- function: `to_duckdb` (line 1385)
- function: `_load_overlay_tagged_paths` (line 1410)
- function: `_build_overlay_context` (line 1447)
- function: `_build_module_row` (line 1498)
- function: `_scip_symbols_and_edges` (line 1551)
- function: `_index_module_safe` (line 1562)
- function: `_read_module_source` (line 1591)
- function: `_collect_outline_nodes` (line 1638)
- function: `_apply_index_results` (line 1670)
- function: `_outline_nodes_for` (line 1710)
- function: `_type_error_count` (line 1750)
- function: `_coverage_value` (line 1755)
- function: `_prepare_config_state` (line 1760)
- function: `_augment_module_rows` (line 1771)
- function: `_build_tag_index` (line 1841)
- function: `_infer_tags` (line 1855)
- function: `_apply_tagging` (line 1862)
- function: `_traits_from_row` (line 1883)
- function: `_build_coverage_rows` (line 1944)
- function: `_build_hotspot_rows` (line 1955)
- function: `_write_exports_outputs` (line 1969)
- function: `_write_graph_outputs` (line 1978)
- function: `_write_uses_output` (line 1985)
- function: `_apply_ownership` (line 1991)
- function: `_write_ownership_output` (line 2020)
- function: `_write_slices_output` (line 2035)
- function: `_write_typedness_output` (line 2072)
- function: `_write_doc_output` (line 2086)
- function: `_write_coverage_output` (line 2100)
- function: `_write_config_output` (line 2104)
- function: `_write_hotspot_output` (line 2108)
- function: `_write_ast_outputs` (line 2112)
- function: `_write_modules_json` (line 2131)
- function: `_write_markdown_modules` (line 2140)
- function: `_write_repo_map` (line 2154)
- function: `_write_symbol_graph` (line 2179)
- function: `_write_tabular_records` (line 2186)
- function: `_collect_ast_artifacts` (line 2191)
- function: `_write_ast_jsonl` (line 2214)
- function: `_normalize_type_signal_map` (line 2219)
- function: `_normalize_metric_map` (line 2235)
- function: `_normalize_path_key` (line 2253)
- function: `_group_configs_by_dir` (line 2257)
- function: `_config_refs_for_row` (line 2268)
- function: `_ancestor_dirs` (line 2284)
- function: `_dir_key_from_path` (line 2299)
- function: `_should_mark_overlay` (line 2306)
- function: `_ensure_package_overlays` (line 2336)
- function: `_normalized_rel_path` (line 2422)
- function: `_write_tag_index` (line 2426)
- function: `main` (line 2441)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 22
- **cycle_group**: 90

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 32
- recent churn 90: 32

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
- loc: 2449

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
