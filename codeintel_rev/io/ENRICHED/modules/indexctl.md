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
- from **kgfoundry_common.logging** import get_logger
- from **(absolute)** import pyarrow.parquet

## Definitions

- variable: `pyarrow_parquet` (line 51)
- variable: `LOGGER` (line 53)
- variable: `app` (line 54)
- variable: `DEFAULT_XTR_ORACLE` (line 55)
- variable: `embeddings_app` (line 56)
- function: `_get_settings` (line 61)
- variable: `RootOption` (line 72)
- variable: `ExtraOption` (line 73)
- variable: `VersionArg` (line 81)
- variable: `PathArg` (line 82)
- variable: `QueriesArg` (line 83)
- variable: `IndexOption` (line 87)
- variable: `AssetsArg` (line 88)
- variable: `SidecarOption` (line 96)
- variable: `VersionOption` (line 104)
- variable: `ParquetOption` (line 108)
- variable: `OutputOption` (line 111)
- variable: `ChunkBatchOption` (line 112)
- variable: `SampleOption` (line 116)
- variable: `EpsilonOption` (line 117)
- variable: `SweepMode` (line 121)
- class: `SearchCommandParams` (line 136)
- variable: `SWEEP_OPTION` (line 148)
- variable: `IdMapOption` (line 153)
- variable: `DuckOption` (line 154)
- variable: `OutOption` (line 155)
- variable: `ParamSpaceArg` (line 156)
- variable: `EvalTopKOption` (line 160)
- variable: `EvalKFactorOption` (line 164)
- variable: `EvalNProbeOption` (line 168)
- variable: `EvalXtrOracleOption` (line 172)
- function: `global_options` (line 182)
- function: `_default_root` (line 187)
- function: `_resolve_root` (line 194)
- function: `_manager` (line 200)
- function: `_build_assets` (line 205)
- function: `_parse_extras` (line 223)
- function: `_parse_sidecars` (line 234)
- function: `_resolve_version_dir` (line 253)
- function: `_manifest_path_for` (line 263)
- function: `_load_manifest` (line 267)
- function: `_write_manifest` (line 277)
- class: `_EmbeddingBuildContext` (line 282)
- function: `_build_context` (line 292)
- function: `_resolve_duck_path` (line 320)
- function: `_resolve_output_path` (line 337)
- function: `_parquet_meta` (line 357)
- function: `_build_embedding_manifest` (line 370)
- function: `_compute_chunk_checksum` (line 396)
- function: `_collect_chunks_and_embeddings` (line 411)
- function: `_deterministic_sample` (line 458)
- function: `_evaluate_drift` (line 492)
- function: `_execute_embeddings_build` (line 517)
- function: `_run_embedding_validation` (line 579)
- function: `_write_embedding_meta` (line 616)
- function: `embeddings_build_command` (line 631)
- function: `embeddings_validate_command` (line 656)
- function: `_parse_tune_overrides` (line 718)
- function: `_faiss_manager` (line 758)
- function: `_duckdb_catalog` (line 772)
- function: `_duckdb_embedding_dim` (line 786)
- function: `_count_idmap_rows` (line 812)
- function: `_load_xtr_index` (line 842)
- function: `_eval_paths` (line 858)
- function: `status_command` (line 868)
- function: `stage_command` (line 878)
- function: `publish_command` (line 935)
- function: `rollback_command` (line 945)
- function: `list_command` (line 955)
- function: `health_command` (line 967)
- function: `export_idmap_command` (line 1026)
- function: `materialize_join_command` (line 1047)
- function: `tune_command` (line 1063)
- function: `tune_params_command` (line 1133)
- function: `show_profile_command` (line 1175)
- function: `_write_tuning_audit` (line 1181)
- function: `_run_autotune` (line 1192)
- function: `eval_command` (line 1218)
- function: `_execute_search` (line 1251)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 12
- **cycle_group**: 132

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

- score: 2.97

## Side Effects

- database
- filesystem

## Complexity

- branches: 103
- cyclomatic: 104
- loc: 1330

## Doc Coverage

- `_get_settings` (function): summary=yes, params=ok, examples=no — Load settings once and reuse for subsequent commands.
- `SearchCommandParams` (class): summary=yes, examples=no — Typed container for CLI-provided semantic search arguments.
- `global_options` (function): summary=yes, params=mismatch, examples=no — Configure shared CLI options.
- `_default_root` (function): summary=no, examples=no
- `_resolve_root` (function): summary=no, examples=no
- `_manager` (function): summary=no, examples=no
- `_build_assets` (function): summary=no, examples=no
- `_parse_extras` (function): summary=no, examples=no
- `_parse_sidecars` (function): summary=no, examples=no
- `_resolve_version_dir` (function): summary=no, examples=no

## Tags

low-coverage
