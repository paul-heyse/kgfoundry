# cli_enrich.py

## Docstring

```
CLI entrypoint for repo enrichment and targeted overlay generation.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import ast
- from **(absolute)** import logging
- from **collections.abc** import Iterable, Mapping
- from **dataclasses** import asdict, dataclass
- from **datetime** import UTC, datetime
- from **fnmatch** import fnmatch
- from **pathlib** import Path
- from **typing** import Annotated, Any, Protocol, cast
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
- from **codeintel_rev.enrich.stubs_overlay** import OverlayPolicy, activate_overlays, deactivate_all, generate_overlay_for_file
- from **codeintel_rev.enrich.tagging** import ModuleTraits, infer_tags, load_rules
- from **codeintel_rev.enrich.tree_sitter_bridge** import build_outline
- from **codeintel_rev.export_resolver** import build_module_name_map, resolve_exports
- from **codeintel_rev.risk_hotspots** import compute_hotspot_score
- from **codeintel_rev.typedness** import FileTypeSignals, collect_type_signals
- from **codeintel_rev.uses_builder** import UseGraph, build_use_graph, write_use_graph
- from **(absolute)** import yaml

## Definitions

- variable: `pl` (line 18)
- variable: `yaml_module` (line 65)
- variable: `LOGGER` (line 68)
- class: `_YamlDumpFn` (line 71)
- variable: `EXPORT_HUB_THRESHOLD` (line 75)
- variable: `OVERLAY_PARAM_THRESHOLD` (line 76)
- variable: `OVERLAY_FAN_IN_THRESHOLD` (line 77)
- variable: `OVERLAY_ERROR_THRESHOLD` (line 78)
- variable: `ROOT` (line 80)
- variable: `SCIP` (line 81)
- variable: `OUT` (line 82)
- variable: `PYREFLY` (line 87)
- variable: `TAGS` (line 92)
- variable: `COVERAGE_XML` (line 93)
- variable: `OnlyPatternsOption` (line 98)
- variable: `SlicesFilterOption` (line 106)
- variable: `DEFAULT_MIN_ERRORS` (line 114)
- variable: `DEFAULT_MAX_OVERLAYS` (line 115)
- variable: `DEFAULT_INCLUDE_PUBLIC_DEFS` (line 116)
- variable: `DEFAULT_INJECT_GETATTR_ANY` (line 117)
- variable: `DEFAULT_DRY_RUN` (line 118)
- variable: `DEFAULT_ACTIVATE` (line 119)
- variable: `DEFAULT_DEACTIVATE` (line 120)
- variable: `DEFAULT_USE_TYPE_ERROR_OVERLAYS` (line 121)
- variable: `DEFAULT_EMIT_AST` (line 122)
- variable: `DEFAULT_MAX_FILE_BYTES` (line 123)
- variable: `DEFAULT_OWNER_HISTORY_DAYS` (line 124)
- variable: `DEFAULT_COMMITS_WINDOW` (line 125)
- variable: `DEFAULT_ENABLE_OWNERS` (line 126)
- variable: `DEFAULT_EMIT_SLICES_FLAG` (line 127)
- variable: `STUBS` (line 129)
- variable: `OVERLAYS_ROOT` (line 134)
- variable: `MIN_ERRORS` (line 139)
- variable: `MAX_OVERLAYS` (line 144)
- variable: `INCLUDE_PUBLIC_DEFS` (line 149)
- variable: `INJECT_GETATTR_ANY` (line 154)
- variable: `DRY_RUN` (line 159)
- variable: `ACTIVATE` (line 164)
- variable: `DEACTIVATE` (line 169)
- variable: `TYPE_ERROR_OVERLAYS` (line 174)
- variable: `OwnersOption` (line 179)
- variable: `HISTORY_WINDOW` (line 186)
- variable: `COMMITS_WINDOW_OPTION` (line 191)
- variable: `EmitSlicesOption` (line 196)
- variable: `MAX_FILE_BYTES` (line 203)
- variable: `app` (line 209)
- class: `ScipContext` (line 213)
- class: `ScanInputs` (line 221)
- class: `PipelineResult` (line 234)
- function: `_iter_files` (line 249)
- function: `_run_pipeline` (line 262)
- function: `run_all` (line 341)
- function: `scan` (line 397)
- function: `exports` (line 441)
- function: `graph` (line 482)
- function: `uses` (line 509)
- function: `typedness` (line 536)
- function: `doc` (line 563)
- function: `coverage` (line 590)
- function: `config` (line 617)
- function: `hotspots` (line 644)
- function: `overlays` (line 671)
- function: `_build_module_row` (line 786)
- function: `_scip_symbols_and_edges` (line 887)
- function: `_outline_nodes_for` (line 898)
- function: `_type_error_count` (line 913)
- function: `_coverage_value` (line 918)
- function: `_augment_module_rows` (line 923)
- function: `_build_tag_index` (line 993)
- function: `_apply_tagging` (line 1007)
- function: `_traits_from_row` (line 1028)
- function: `_build_coverage_rows` (line 1089)
- function: `_build_hotspot_rows` (line 1100)
- function: `_write_exports_outputs` (line 1114)
- function: `_write_graph_outputs` (line 1121)
- function: `_write_uses_output` (line 1126)
- function: `_apply_ownership` (line 1130)
- function: `_write_ownership_output` (line 1159)
- function: `_write_slices_output` (line 1174)
- function: `_write_typedness_output` (line 1205)
- function: `_write_doc_output` (line 1219)
- function: `_write_coverage_output` (line 1233)
- function: `_write_config_output` (line 1237)
- function: `_write_hotspot_output` (line 1241)
- function: `_write_ast_outputs` (line 1245)
- function: `_write_modules_json` (line 1264)
- function: `_write_markdown_modules` (line 1268)
- function: `_write_repo_map` (line 1279)
- function: `_write_symbol_graph` (line 1295)
- function: `_write_tabular_records` (line 1302)
- function: `_collect_ast_artifacts` (line 1309)
- function: `_write_ast_jsonl` (line 1332)
- function: `_normalize_type_signal_map` (line 1337)
- function: `_normalize_metric_map` (line 1353)
- function: `_normalize_path_key` (line 1371)
- function: `_group_configs_by_dir` (line 1375)
- function: `_config_refs_for_row` (line 1386)
- function: `_ancestor_dirs` (line 1402)
- function: `_dir_key_from_path` (line 1417)
- function: `_should_mark_overlay` (line 1424)
- function: `_ensure_package_overlays` (line 1455)
- function: `_normalized_rel_path` (line 1539)
- function: `_write_tag_index` (line 1543)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 18
- **cycle_group**: 23

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 15
- recent churn 90: 15

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

- score: 3.24

## Side Effects

- filesystem

## Complexity

- branches: 154
- cyclomatic: 155
- loc: 1560

## Doc Coverage

- `_YamlDumpFn` (class): summary=no, examples=no
- `ScipContext` (class): summary=yes, examples=no — Cache of SCIP lookups used during scanning.
- `ScanInputs` (class): summary=yes, examples=no — Bundle of contextual inputs used during module row construction.
- `PipelineResult` (class): summary=yes, examples=no — Aggregate artifact bundle produced by a pipeline run.
- `_iter_files` (function): summary=no, examples=no
- `_run_pipeline` (function): summary=no, examples=no
- `run_all` (function): summary=yes, params=mismatch, examples=no — Run the full enrichment pipeline and emit all artifacts.
- `scan` (function): summary=yes, params=mismatch, examples=no — Backward-compatible alias for ``all``.
- `exports` (function): summary=yes, params=mismatch, examples=no — Emit modules.jsonl, repo map, tag index, and Markdown module sheets.
- `graph` (function): summary=yes, params=mismatch, examples=no — Emit symbol and import graph artifacts.

## Tags

low-coverage
