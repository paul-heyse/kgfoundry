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
- from **codeintel_rev.enrich.ast_indexer** import AstMetricsRow, AstNodeRow, collect_ast_nodes_from_tree, compute_ast_metrics, empty_metrics_row, write_ast_parquet
- from **codeintel_rev.enrich.duckdb_store** import DuckConn, ingest_modules_jsonl
- from **codeintel_rev.enrich.errors** import IngestError, StageError, TaggingError, TypeSignalError
- from **codeintel_rev.enrich.graph_builder** import ImportGraph, build_import_graph, write_import_graph
- from **codeintel_rev.enrich.models** import ModuleRecord
- from **codeintel_rev.enrich.output_writers** import write_json, write_jsonl, write_markdown_module, write_parquet, write_parquet_dataset
- from **codeintel_rev.enrich.ownership** import OwnershipIndex, compute_ownership
- from **codeintel_rev.enrich.pathnorm** import detect_repo_root
- from **codeintel_rev.enrich.pipeline_helpers** import apply_tagging
- from **codeintel_rev.enrich.pipeline_helpers** import build_module_row
- from **codeintel_rev.enrich.pipeline_helpers** import normalized_rel_path
- from **codeintel_rev.enrich.pipeline_helpers** import outline_nodes_for
- from **codeintel_rev.enrich.pipeline_helpers** import type_error_count
- from **codeintel_rev.enrich.scip_reader** import Document, SCIPIndex
- from **codeintel_rev.enrich.slices_builder** import build_slice_record, write_slice
- from **codeintel_rev.enrich.stubs_overlay** import OverlayInputs, OverlayPolicy, generate_overlay_for_file
- from **codeintel_rev.enrich.tagging** import load_rules
- from **codeintel_rev.enrich.validators** import ModuleRecordModel
- from **codeintel_rev.export_resolver** import build_module_name_map, resolve_exports
- from **codeintel_rev.risk_hotspots** import compute_hotspot_score
- from **codeintel_rev.typedness** import FileTypeSignals, collect_type_signals
- from **codeintel_rev.uses_builder** import UseGraph, build_use_graph, write_use_graph
- from **(absolute)** import yaml

## Definitions

- variable: `yaml_module` (line 81)
- function: `_yaml_errors` (line 84)
- variable: `YAML_ERRORS` (line 97)
- variable: `LOGGER` (line 100)
- function: `_attach_argv_normalizer` (line 103)
- function: `_format_stage_meta` (line 111)
- function: `_stage_span` (line 117)
- class: `StageMeta` (line 169)
- function: `_stage` (line 177)
- class: `_YamlDumpKwargs` (line 208)
- class: `_YamlDumpFn` (line 212)
- variable: `EXPORT_HUB_THRESHOLD` (line 220)
- variable: `OVERLAY_PARAM_THRESHOLD` (line 221)
- variable: `OVERLAY_FAN_IN_THRESHOLD` (line 222)
- variable: `OVERLAY_ERROR_THRESHOLD` (line 223)
- variable: `DEFAULT_MIN_ERRORS` (line 225)
- variable: `DEFAULT_MAX_OVERLAYS` (line 226)
- variable: `DEFAULT_INCLUDE_PUBLIC_DEFS` (line 227)
- variable: `DEFAULT_INJECT_GETATTR_ANY` (line 228)
- variable: `DEFAULT_DRY_RUN` (line 229)
- variable: `DEFAULT_ACTIVATE` (line 230)
- variable: `DEFAULT_DEACTIVATE` (line 231)
- variable: `DEFAULT_USE_TYPE_ERROR_OVERLAYS` (line 232)
- variable: `DEFAULT_EMIT_AST` (line 233)
- variable: `DEFAULT_MAX_FILE_BYTES` (line 234)
- variable: `DEFAULT_OWNER_HISTORY_DAYS` (line 235)
- variable: `DEFAULT_COMMITS_WINDOW` (line 236)
- variable: `DEFAULT_ENABLE_OWNERS` (line 237)
- variable: `DEFAULT_EMIT_SLICES_FLAG` (line 238)
- class: `PipelineOptions` (line 244)
- class: `AnalyticsOptions` (line 258)
- class: `CLIContextState` (line 269)
- variable: `ROOT_OPTION` (line 276)
- variable: `SCIP_OPTION` (line 285)
- variable: `OUT_OPTION` (line 293)
- variable: `PYREFLY_OPTION` (line 299)
- variable: `TAGS_OPTION` (line 307)
- variable: `COVERAGE_OPTION` (line 315)
- variable: `ONLY_OPTION` (line 321)
- variable: `MAX_FILE_BYTES_OPTION` (line 326)
- variable: `OWNERS_OPTION` (line 331)
- variable: `HISTORY_WINDOW_OPTION` (line 336)
- variable: `COMMITS_WINDOW_OPTION` (line 341)
- variable: `EMIT_SLICES_OPTION` (line 346)
- variable: `SLICES_FILTER_OPTION` (line 351)
- variable: `EMIT_AST_OPTION` (line 356)
- variable: `OVERLAYS_CONFIG_OPTION` (line 361)
- variable: `OVERLAYS_SET_OPTION` (line 366)
- variable: `DRY_RUN_OPTION` (line 372)
- variable: `GLOBAL_OPTIONS_HELP` (line 379)
- function: `normalize_global_cli_args` (line 412)
- variable: `app` (line 456)
- function: `shared_options` (line 461)
- function: `_ensure_state` (line 499)
- class: `OverlayCLIOptions` (line 508)
- class: `OverlayContext` (line 524)
- function: `_load_overlay_options` (line 537)
- function: `_read_overlay_config` (line 552)
- function: `_parse_bool` (line 568)
- function: `_resolve_path` (line 581)
- function: `_parse_int_option` (line 587)
- function: `_parse_path_option` (line 600)
- function: `_set_overlay_option` (line 609)
- class: `ScipContext` (line 635)
- class: `ScanInputs` (line 643)
- class: `PipelineContext` (line 656)
- class: `PipelineResult` (line 671)
- class: `PreparedPipeline` (line 687)
- class: `AnalyticsArtifacts` (line 695)
- class: `ConfigReferenceState` (line 707)
- function: `_discover_py_files` (line 715)
- function: `_load_scip_artifacts` (line 739)
- function: `_collect_type_signal_map` (line 768)
- function: `_collect_coverage_map` (line 808)
- function: `_index_config_records` (line 835)
- function: `_load_tagging_rules` (line 855)
- function: `_should_skip_candidate` (line 888)
- function: `_iter_files` (line 899)
- function: `_prepare_pipeline` (line 911)
- function: `_compute_pipeline_analytics` (line 940)
- function: `_run_pipeline` (line 968)
- function: `_execute_pipeline` (line 987)
- function: `_execute_pipeline_or_exit` (line 994)
- function: `_handle_dry_run` (line 1004)
- function: `_scan_modules` (line 1043)
- function: `run_all` (line 1069)
- function: `run` (line 1105)
- function: `scan` (line 1116)
- function: `exports` (line 1128)
- function: `to_duckdb` (line 1155)
- function: `_load_overlay_tagged_paths` (line 1180)
- function: `_build_overlay_context` (line 1217)
- function: `_prepare_config_state` (line 1268)
- function: `_augment_module_rows` (line 1279)
- function: `_build_tag_index` (line 1349)
- function: `_infer_tags` (line 1363)
- function: `_build_coverage_rows` (line 1370)
- function: `_build_hotspot_rows` (line 1381)
- function: `_write_exports_outputs` (line 1395)
- function: `_write_graph_outputs` (line 1404)
- function: `_write_uses_output` (line 1411)
- function: `_apply_ownership` (line 1417)
- function: `_write_ownership_output` (line 1446)
- function: `_write_slices_output` (line 1461)
- function: `_write_typedness_output` (line 1498)
- function: `_write_doc_output` (line 1512)
- function: `_write_coverage_output` (line 1526)
- function: `_write_config_output` (line 1530)
- function: `_write_hotspot_output` (line 1534)
- function: `_write_ast_outputs` (line 1538)
- function: `_write_modules_json` (line 1557)
- function: `_write_markdown_modules` (line 1566)
- function: `_write_repo_map` (line 1580)
- function: `_write_symbol_graph` (line 1605)
- function: `_write_tabular_records` (line 1612)
- function: `_collect_ast_artifacts` (line 1617)
- function: `_write_ast_jsonl` (line 1640)
- function: `_normalize_type_signal_map` (line 1645)
- function: `_normalize_metric_map` (line 1661)
- function: `_normalize_path_key` (line 1679)
- function: `_group_configs_by_dir` (line 1683)
- function: `_config_refs_for_row` (line 1694)
- function: `_ancestor_dirs` (line 1710)
- function: `_dir_key_from_path` (line 1725)
- function: `_should_mark_overlay` (line 1732)
- function: `_ensure_package_overlays` (line 1762)
- function: `_write_tag_index` (line 1848)
- variable: `attach_argv_normalizer` (line 1864)
- variable: `execute_pipeline_or_exit` (line 1865)
- variable: `handle_dry_run` (line 1866)
- variable: `write_graph_outputs` (line 1867)
- variable: `write_uses_output` (line 1868)
- variable: `write_typedness_output` (line 1869)
- variable: `write_doc_output` (line 1870)
- variable: `write_coverage_output` (line 1871)
- variable: `write_config_output` (line 1872)
- variable: `write_hotspot_output` (line 1873)
- variable: `ensure_state` (line 1874)
- variable: `load_overlay_options` (line 1875)
- variable: `build_overlay_context` (line 1876)
- variable: `iter_files` (line 1877)
- variable: `normalized_rel_path` (line 1878)
- variable: `ensure_package_overlays` (line 1879)
- variable: `build_module_row` (line 1880)
- variable: `outline_nodes_for` (line 1881)
- variable: `type_error_count` (line 1882)
- variable: `apply_tagging` (line 1883)
- function: `main` (line 1886)

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 21
- **cycle_group**: 83

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 2
- recent churn 90: 2

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

- score: 3.40

## Side Effects

- filesystem

## Complexity

- branches: 184
- cyclomatic: 185
- loc: 1894

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
