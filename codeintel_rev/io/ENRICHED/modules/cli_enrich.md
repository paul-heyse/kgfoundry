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
- from **dataclasses** import asdict, dataclass, field
- from **datetime** import UTC, datetime
- from **fnmatch** import fnmatch
- from **pathlib** import Path
- from **typing** import Annotated, Any, Protocol, cast
- from **(absolute)** import polars
- from **(absolute)** import typer
- from **codeintel_rev.config_indexer** import index_config_files
- from **codeintel_rev.coverage_ingest** import collect_coverage
- from **codeintel_rev.enrich.ast_indexer** import AstMetricsRow, AstNodeRow, collect_ast_nodes_from_tree, compute_ast_metrics, empty_metrics_row, stable_module_path, write_ast_parquet
- from **codeintel_rev.enrich.duckdb_store** import DuckConn, ingest_modules_jsonl
- from **codeintel_rev.enrich.errors** import IndexingError, IngestError, StageError, TaggingError, TypeSignalError
- from **codeintel_rev.enrich.graph_builder** import ImportGraph, build_import_graph, write_import_graph
- from **codeintel_rev.enrich.libcst_bridge** import ModuleIndex, index_module
- from **codeintel_rev.enrich.models** import ModuleRecord
- from **codeintel_rev.enrich.output_writers** import write_json, write_jsonl, write_markdown_module, write_parquet
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

- variable: `pl` (line 21)
- variable: `yaml_module` (line 79)
- variable: `LOGGER` (line 82)
- function: `_format_stage_meta` (line 85)
- function: `_stage_span` (line 91)
- class: `_YamlDumpFn` (line 132)
- variable: `EXPORT_HUB_THRESHOLD` (line 136)
- variable: `OVERLAY_PARAM_THRESHOLD` (line 137)
- variable: `OVERLAY_FAN_IN_THRESHOLD` (line 138)
- variable: `OVERLAY_ERROR_THRESHOLD` (line 139)
- variable: `DEFAULT_MIN_ERRORS` (line 141)
- variable: `DEFAULT_MAX_OVERLAYS` (line 142)
- variable: `DEFAULT_INCLUDE_PUBLIC_DEFS` (line 143)
- variable: `DEFAULT_INJECT_GETATTR_ANY` (line 144)
- variable: `DEFAULT_DRY_RUN` (line 145)
- variable: `DEFAULT_ACTIVATE` (line 146)
- variable: `DEFAULT_DEACTIVATE` (line 147)
- variable: `DEFAULT_USE_TYPE_ERROR_OVERLAYS` (line 148)
- variable: `DEFAULT_EMIT_AST` (line 149)
- variable: `DEFAULT_MAX_FILE_BYTES` (line 150)
- variable: `DEFAULT_OWNER_HISTORY_DAYS` (line 151)
- variable: `DEFAULT_COMMITS_WINDOW` (line 152)
- variable: `DEFAULT_ENABLE_OWNERS` (line 153)
- variable: `DEFAULT_EMIT_SLICES_FLAG` (line 154)
- class: `PipelineOptions` (line 160)
- class: `AnalyticsOptions` (line 174)
- class: `CLIContextState` (line 185)
- variable: `ROOT_OPTION` (line 192)
- variable: `SCIP_OPTION` (line 201)
- variable: `OUT_OPTION` (line 209)
- variable: `PYREFLY_OPTION` (line 215)
- variable: `TAGS_OPTION` (line 223)
- variable: `COVERAGE_OPTION` (line 231)
- variable: `ONLY_OPTION` (line 237)
- variable: `MAX_FILE_BYTES_OPTION` (line 242)
- variable: `OWNERS_OPTION` (line 247)
- variable: `HISTORY_WINDOW_OPTION` (line 252)
- variable: `COMMITS_WINDOW_OPTION` (line 257)
- variable: `EMIT_SLICES_OPTION` (line 262)
- variable: `SLICES_FILTER_OPTION` (line 267)
- variable: `EMIT_AST_OPTION` (line 272)
- variable: `OVERLAYS_CONFIG_OPTION` (line 277)
- variable: `OVERLAYS_SET_OPTION` (line 282)
- variable: `app` (line 290)
- function: `_ensure_state` (line 293)
- function: `global_options` (line 302)
- class: `OverlayCLIOptions` (line 341)
- class: `OverlayContext` (line 357)
- function: `_load_overlay_options` (line 370)
- function: `_read_overlay_config` (line 385)
- function: `_parse_bool` (line 401)
- function: `_resolve_path` (line 414)
- function: `_parse_int_option` (line 420)
- function: `_parse_path_option` (line 433)
- function: `_set_overlay_option` (line 442)
- class: `ScipContext` (line 468)
- class: `ScanInputs` (line 476)
- class: `PipelineContext` (line 489)
- class: `PipelineResult` (line 504)
- function: `_discover_py_files` (line 519)
- function: `_load_scip_artifacts` (line 543)
- function: `_collect_type_signal_map` (line 572)
- function: `_collect_coverage_map` (line 612)
- function: `_index_config_records` (line 637)
- function: `_load_tagging_rules` (line 657)
- function: `_iter_files` (line 687)
- function: `_run_pipeline` (line 699)
- function: `_execute_pipeline` (line 759)
- function: `_execute_pipeline_or_exit` (line 766)
- function: `_scan_modules` (line 776)
- function: `run_all` (line 802)
- function: `run` (line 835)
- function: `scan` (line 845)
- function: `exports` (line 856)
- function: `graph` (line 877)
- function: `uses` (line 885)
- function: `typedness` (line 893)
- function: `doc` (line 901)
- function: `coverage` (line 909)
- function: `config` (line 917)
- function: `hotspots` (line 925)
- function: `overlays` (line 933)
- function: `to_duckdb` (line 1065)
- function: `_build_overlay_context` (line 1090)
- function: `_build_module_row` (line 1134)
- function: `_scip_symbols_and_edges` (line 1187)
- function: `_index_module_safe` (line 1198)
- function: `_read_module_source` (line 1227)
- function: `_collect_outline_nodes` (line 1274)
- function: `_apply_index_results` (line 1306)
- function: `_outline_nodes_for` (line 1346)
- function: `_type_error_count` (line 1386)
- function: `_coverage_value` (line 1391)
- function: `_augment_module_rows` (line 1396)
- function: `_build_tag_index` (line 1468)
- function: `_infer_tags` (line 1482)
- function: `_apply_tagging` (line 1489)
- function: `_traits_from_row` (line 1510)
- function: `_build_coverage_rows` (line 1571)
- function: `_build_hotspot_rows` (line 1582)
- function: `_write_exports_outputs` (line 1596)
- function: `_write_graph_outputs` (line 1605)
- function: `_write_uses_output` (line 1612)
- function: `_apply_ownership` (line 1618)
- function: `_write_ownership_output` (line 1647)
- function: `_write_slices_output` (line 1662)
- function: `_write_typedness_output` (line 1693)
- function: `_write_doc_output` (line 1707)
- function: `_write_coverage_output` (line 1721)
- function: `_write_config_output` (line 1725)
- function: `_write_hotspot_output` (line 1729)
- function: `_write_ast_outputs` (line 1733)
- function: `_write_modules_json` (line 1752)
- function: `_write_markdown_modules` (line 1761)
- function: `_write_repo_map` (line 1775)
- function: `_write_symbol_graph` (line 1800)
- function: `_write_tabular_records` (line 1807)
- function: `_collect_ast_artifacts` (line 1814)
- function: `_write_ast_jsonl` (line 1837)
- function: `_normalize_type_signal_map` (line 1842)
- function: `_normalize_metric_map` (line 1858)
- function: `_normalize_path_key` (line 1876)
- function: `_group_configs_by_dir` (line 1880)
- function: `_config_refs_for_row` (line 1891)
- function: `_ancestor_dirs` (line 1907)
- function: `_dir_key_from_path` (line 1922)
- function: `_should_mark_overlay` (line 1929)
- function: `_ensure_package_overlays` (line 1959)
- function: `_normalized_rel_path` (line 2045)
- function: `_write_tag_index` (line 2049)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 22
- **cycle_group**: 106

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

- score: 3.42

## Side Effects

- filesystem

## Complexity

- branches: 216
- cyclomatic: 217
- loc: 2066

## Doc Coverage

- `_format_stage_meta` (function): summary=no, examples=no
- `_stage_span` (function): summary=yes, params=mismatch, examples=no — Context manager logging structured stage timings.
- `_YamlDumpFn` (class): summary=no, examples=no
- `PipelineOptions` (class): summary=yes, examples=no — Resolved paths and filters required for pipeline execution.
- `AnalyticsOptions` (class): summary=yes, examples=no — Optional analytics toggles shared across commands.
- `CLIContextState` (class): summary=yes, examples=no — CLI-scoped state shared between commands.
- `_ensure_state` (function): summary=no, examples=no
- `global_options` (function): summary=yes, params=mismatch, examples=no — Capture shared pipeline + analytics options for all commands.
- `OverlayCLIOptions` (class): summary=yes, examples=no — Mutable overlay generation options parsed from CLI/config.
- `OverlayContext` (class): summary=yes, examples=no — Aggregated context used during overlay generation.

## Tags

low-coverage
