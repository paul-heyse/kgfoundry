# cli/indexctl.py

## Docstring

```
Typer CLI for managing index lifecycle operations.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import hashlib
- from **(absolute)** import json
- from **(absolute)** import os
- from **(absolute)** import uuid
- from **collections.abc** import Callable, Mapping, Sequence
- from **contextlib** import suppress
- from **dataclasses** import dataclass
- from **datetime** import UTC, datetime
- from **functools** import lru_cache
- from **pathlib** import Path
- from **typing** import Annotated, Literal, cast
- from **(absolute)** import click
- from **(absolute)** import duckdb
- from **(absolute)** import numpy
- from **(absolute)** import typer
- from **codeintel_rev.config.settings** import Settings, load_settings
- from **codeintel_rev.embeddings** import EmbeddingProvider, get_embedding_provider
- from **codeintel_rev.errors** import RuntimeLifecycleError
- from **codeintel_rev.eval.hybrid_evaluator** import EvalConfig, HybridPoolEvaluator
- from **codeintel_rev.indexing.cast_chunker** import Chunk
- from **codeintel_rev.indexing.index_lifecycle** import IndexAssets, IndexLifecycleManager, collect_asset_attrs
- from **codeintel_rev.io.duckdb_catalog** import DuckDBCatalog
- from **codeintel_rev.io.duckdb_manager** import DuckDBManager
- from **codeintel_rev.io.faiss_manager** import FAISSManager, RefineSearchConfig, SearchRuntimeOverrides
- from **codeintel_rev.io.parquet_store** import ParquetWriteOptions, extract_embeddings, read_chunks_parquet, write_chunks_parquet
- from **codeintel_rev.io.xtr_manager** import XTRIndex
- from **codeintel_rev.typing** import NDArrayF32
- from **(absolute)** import pyarrow.parquet

## Definitions

- variable: `pyarrow_parquet` (line 51)
- variable: `app` (line 53)
- variable: `DEFAULT_XTR_ORACLE` (line 54)
- variable: `embeddings_app` (line 55)
- function: `_cached_settings` (line 60)
- function: `_default_faiss_manager_factory` (line 64)
- function: `_default_duckdb_catalog_factory` (line 79)
- function: `_default_duckdb_embedding_dim` (line 95)
- function: `_default_count_idmap_rows` (line 107)
- function: `_default_embedding_provider_factory` (line 117)
- class: `IndexctlCliContext` (line 122)
- function: `_cli_context` (line 154)
- function: `_get_settings` (line 166)
- variable: `RootOption` (line 170)
- variable: `ExtraOption` (line 171)
- variable: `VersionArg` (line 179)
- variable: `PathArg` (line 180)
- variable: `QueriesArg` (line 181)
- variable: `IndexOption` (line 185)
- variable: `AssetsArg` (line 186)
- variable: `SidecarOption` (line 194)
- variable: `VersionOption` (line 202)
- variable: `ParquetOption` (line 206)
- variable: `OutputOption` (line 209)
- variable: `ChunkBatchOption` (line 210)
- variable: `SampleOption` (line 214)
- variable: `EpsilonOption` (line 215)
- variable: `SweepMode` (line 219)
- class: `SearchCommandParams` (line 234)
- variable: `SWEEP_OPTION` (line 246)
- variable: `IdMapOption` (line 251)
- variable: `DuckOption` (line 252)
- variable: `OutOption` (line 253)
- variable: `ParamSpaceArg` (line 254)
- variable: `EvalTopKOption` (line 258)
- variable: `EvalKFactorOption` (line 262)
- variable: `EvalNProbeOption` (line 266)
- variable: `EvalXtrOracleOption` (line 270)
- function: `global_options` (line 280)
- function: `_default_root` (line 288)
- function: `_resolve_root` (line 295)
- function: `_manager` (line 301)
- function: `_build_assets` (line 306)
- function: `_parse_extras` (line 324)
- function: `_parse_sidecars` (line 334)
- function: `_resolve_version_dir` (line 348)
- function: `_manifest_path_for` (line 358)
- function: `_load_manifest` (line 362)
- function: `_write_manifest` (line 371)
- class: `_EmbeddingBuildContext` (line 376)
- function: `_build_context` (line 386)
- function: `_resolve_duck_path` (line 414)
- function: `_resolve_output_path` (line 431)
- function: `_parquet_meta` (line 451)
- function: `_build_embedding_manifest` (line 464)
- function: `_compute_chunk_checksum` (line 490)
- function: `_collect_chunks_and_embeddings` (line 505)
- function: `_deterministic_sample` (line 552)
- function: `_evaluate_drift` (line 586)
- function: `_execute_embeddings_build` (line 611)
- function: `_run_embedding_validation` (line 673)
- function: `_write_embedding_meta` (line 710)
- function: `embeddings_build_command` (line 721)
- function: `embeddings_validate_command` (line 746)
- function: `_parse_tune_overrides` (line 808)
- function: `_faiss_manager` (line 848)
- function: `_duckdb_catalog` (line 853)
- function: `_duckdb_embedding_dim` (line 858)
- function: `_count_idmap_rows` (line 876)
- function: `_embedding_provider` (line 894)
- function: `_load_xtr_index` (line 898)
- function: `_eval_paths` (line 912)
- function: `status_command` (line 922)
- function: `stage_command` (line 932)
- function: `publish_command` (line 989)
- function: `rollback_command` (line 999)
- function: `list_command` (line 1009)
- function: `health_command` (line 1021)
- function: `export_idmap_command` (line 1080)
- function: `materialize_join_command` (line 1101)
- function: `tune_command` (line 1117)
- function: `tune_params_command` (line 1187)
- function: `show_profile_command` (line 1229)
- function: `_write_tuning_audit` (line 1235)
- function: `_run_autotune` (line 1246)
- function: `eval_command` (line 1272)
- function: `_execute_search` (line 1300)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 12
- **cycle_group**: 88

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 19
- recent churn 90: 19

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Typer CLI for managing index lifecycle operations.
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

- score: 2.98

## Side Effects

- database
- filesystem

## Complexity

- branches: 107
- cyclomatic: 108
- loc: 1379

## Doc Coverage

- `_cached_settings` (function): summary=no, examples=no
- `_default_faiss_manager_factory` (function): summary=no, examples=no
- `_default_duckdb_catalog_factory` (function): summary=no, examples=no
- `_default_duckdb_embedding_dim` (function): summary=no, examples=no
- `_default_count_idmap_rows` (function): summary=no, examples=no
- `_default_embedding_provider_factory` (function): summary=no, examples=no
- `IndexctlCliContext` (class): summary=yes, examples=no — Dependency injection context for the indexctl CLI.
- `_cli_context` (function): summary=no, examples=no
- `_get_settings` (function): summary=no, examples=no
- `SearchCommandParams` (class): summary=yes, examples=no — Typed container for CLI-provided semantic search arguments.

## Tags

low-coverage
