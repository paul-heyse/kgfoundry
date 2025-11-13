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
- from **codeintel_rev.io.faiss_manager** import FAISSManager, SearchRuntimeOverrides
- from **codeintel_rev.io.parquet_store** import ParquetWriteOptions, extract_embeddings, read_chunks_parquet, write_chunks_parquet
- from **codeintel_rev.io.xtr_manager** import XTRIndex
- from **codeintel_rev.typing** import NDArrayF32
- from **kgfoundry_common.logging** import get_logger
- from **(absolute)** import pyarrow.parquet

## Definitions

- variable: `pyarrow_parquet` (line 47)
- variable: `LOGGER` (line 49)
- variable: `app` (line 50)
- variable: `DEFAULT_XTR_ORACLE` (line 51)
- variable: `embeddings_app` (line 52)
- function: `_get_settings` (line 57)
- variable: `RootOption` (line 68)
- variable: `ExtraOption` (line 69)
- variable: `VersionArg` (line 77)
- variable: `PathArg` (line 78)
- variable: `QueriesArg` (line 79)
- variable: `IndexOption` (line 83)
- variable: `AssetsArg` (line 84)
- variable: `SidecarOption` (line 92)
- variable: `VersionOption` (line 100)
- variable: `ParquetOption` (line 104)
- variable: `OutputOption` (line 107)
- variable: `ChunkBatchOption` (line 108)
- variable: `SampleOption` (line 112)
- variable: `EpsilonOption` (line 113)
- variable: `SweepMode` (line 117)
- variable: `SWEEP_OPTION` (line 130)
- variable: `IdMapOption` (line 135)
- variable: `DuckOption` (line 136)
- variable: `OutOption` (line 137)
- variable: `ParamSpaceArg` (line 138)
- variable: `EvalTopKOption` (line 142)
- variable: `EvalKFactorOption` (line 146)
- variable: `EvalNProbeOption` (line 150)
- variable: `EvalXtrOracleOption` (line 154)
- function: `global_options` (line 164)
- function: `_default_root` (line 169)
- function: `_resolve_root` (line 176)
- function: `_manager` (line 182)
- function: `_build_assets` (line 187)
- function: `_parse_extras` (line 205)
- function: `_parse_sidecars` (line 216)
- function: `_resolve_version_dir` (line 235)
- function: `_manifest_path_for` (line 245)
- function: `_load_manifest` (line 249)
- function: `_write_manifest` (line 259)
- class: `_EmbeddingBuildContext` (line 264)
- function: `_build_context` (line 274)
- function: `_resolve_duck_path` (line 302)
- function: `_resolve_output_path` (line 319)
- function: `_parquet_meta` (line 339)
- function: `_build_embedding_manifest` (line 352)
- function: `_compute_chunk_checksum` (line 378)
- function: `_collect_chunks_and_embeddings` (line 393)
- function: `_deterministic_sample` (line 440)
- function: `_evaluate_drift` (line 474)
- function: `_execute_embeddings_build` (line 499)
- function: `_run_embedding_validation` (line 561)
- function: `_write_embedding_meta` (line 598)
- function: `embeddings_build_command` (line 613)
- function: `embeddings_validate_command` (line 638)
- function: `_parse_tune_overrides` (line 700)
- function: `_faiss_manager` (line 740)
- function: `_duckdb_catalog` (line 754)
- function: `_duckdb_embedding_dim` (line 768)
- function: `_count_idmap_rows` (line 794)
- function: `_load_xtr_index` (line 824)
- function: `_eval_paths` (line 840)
- function: `status_command` (line 850)
- function: `stage_command` (line 860)
- function: `publish_command` (line 917)
- function: `rollback_command` (line 927)
- function: `list_command` (line 937)
- function: `health_command` (line 949)
- function: `export_idmap_command` (line 1004)
- function: `materialize_join_command` (line 1025)
- function: `tune_command` (line 1041)
- function: `tune_params_command` (line 1111)
- function: `show_profile_command` (line 1153)
- function: `_write_tuning_audit` (line 1159)
- function: `_run_autotune` (line 1170)
- function: `eval_command` (line 1196)
- function: `search_command` (line 1230)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 12
- **cycle_group**: 132

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 12
- recent churn 90: 12

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

- branches: 102
- cyclomatic: 103
- loc: 1323

## Doc Coverage

- `_get_settings` (function): summary=yes, params=ok, examples=no — Load settings once and reuse for subsequent commands.
- `global_options` (function): summary=yes, params=mismatch, examples=no — Configure shared CLI options.
- `_default_root` (function): summary=no, examples=no
- `_resolve_root` (function): summary=no, examples=no
- `_manager` (function): summary=no, examples=no
- `_build_assets` (function): summary=no, examples=no
- `_parse_extras` (function): summary=no, examples=no
- `_parse_sidecars` (function): summary=no, examples=no
- `_resolve_version_dir` (function): summary=no, examples=no
- `_manifest_path_for` (function): summary=no, examples=no

## Tags

low-coverage
