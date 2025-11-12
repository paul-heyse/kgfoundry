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
- variable: `STUBS` (line 127)
- variable: `OVERLAYS_ROOT` (line 132)
- variable: `MIN_ERRORS` (line 137)
- variable: `MAX_OVERLAYS` (line 142)
- variable: `INCLUDE_PUBLIC_DEFS` (line 147)
- variable: `INJECT_GETATTR_ANY` (line 152)
- variable: `DRY_RUN` (line 157)
- variable: `ACTIVATE` (line 162)
- variable: `DEACTIVATE` (line 167)
- variable: `TYPE_ERROR_OVERLAYS` (line 172)
- variable: `OWNERS` (line 177)
- variable: `HISTORY_WINDOW` (line 182)
- variable: `COMMITS_WINDOW_OPTION` (line 187)
- variable: `EMIT_SLICES` (line 192)
- variable: `MAX_FILE_BYTES` (line 197)
- variable: `app` (line 203)
- class: `ScipContext` (line 207)
- class: `ScanInputs` (line 215)
- class: `PipelineResult` (line 228)
- function: `_iter_files` (line 243)
- function: `_run_pipeline` (line 256)
- function: `run_all` (line 335)
- function: `scan` (line 391)
- function: `exports` (line 435)
- function: `graph` (line 476)
- function: `uses` (line 503)
- function: `typedness` (line 530)
- function: `doc` (line 557)
- function: `coverage` (line 584)
- function: `config` (line 611)
- function: `hotspots` (line 638)
- function: `overlays` (line 665)
- function: `_build_module_row` (line 780)
- function: `_augment_module_rows` (line 901)
- function: `_build_tag_index` (line 971)
- function: `_apply_tagging` (line 985)
- function: `_traits_from_row` (line 1006)
- function: `_build_coverage_rows` (line 1067)
- function: `_build_hotspot_rows` (line 1078)
- function: `_write_exports_outputs` (line 1092)
- function: `_write_graph_outputs` (line 1099)
- function: `_write_uses_output` (line 1104)
- function: `_apply_ownership` (line 1108)
- function: `_write_ownership_output` (line 1137)
- function: `_write_slices_output` (line 1152)
- function: `_write_typedness_output` (line 1183)
- function: `_write_doc_output` (line 1197)
- function: `_write_coverage_output` (line 1211)
- function: `_write_config_output` (line 1215)
- function: `_write_hotspot_output` (line 1219)
- function: `_write_ast_outputs` (line 1223)
- function: `_write_modules_json` (line 1242)
- function: `_write_markdown_modules` (line 1246)
- function: `_write_repo_map` (line 1257)
- function: `_write_symbol_graph` (line 1273)
- function: `_write_tabular_records` (line 1280)
- function: `_collect_ast_artifacts` (line 1287)
- function: `_write_ast_jsonl` (line 1310)
- function: `_normalize_type_signal_map` (line 1315)
- function: `_normalize_metric_map` (line 1331)
- function: `_normalize_path_key` (line 1349)
- function: `_group_configs_by_dir` (line 1353)
- function: `_config_refs_for_row` (line 1364)
- function: `_ancestor_dirs` (line 1380)
- function: `_dir_key_from_path` (line 1395)
- function: `_should_mark_overlay` (line 1402)
- function: `_ensure_package_overlays` (line 1433)
- function: `_normalized_rel_path` (line 1517)
- function: `_write_tag_index` (line 1521)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 18
- **cycle_group**: 23

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 13
- recent churn 90: 13

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
- loc: 1538

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
