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
- function: `_get_settings` (line 60)
- variable: `RootOption` (line 71)
- variable: `ExtraOption` (line 72)
- variable: `VersionArg` (line 80)
- variable: `PathArg` (line 81)
- variable: `QueriesArg` (line 82)
- variable: `IndexOption` (line 86)
- variable: `AssetsArg` (line 87)
- variable: `SidecarOption` (line 95)
- variable: `VersionOption` (line 103)
- variable: `ParquetOption` (line 107)
- variable: `OutputOption` (line 110)
- variable: `ChunkBatchOption` (line 111)
- variable: `SampleOption` (line 115)
- variable: `EpsilonOption` (line 116)
- variable: `SweepMode` (line 120)
- class: `SearchCommandParams` (line 135)
- variable: `SWEEP_OPTION` (line 147)
- variable: `IdMapOption` (line 152)
- variable: `DuckOption` (line 153)
- variable: `OutOption` (line 154)
- variable: `ParamSpaceArg` (line 155)
- variable: `EvalTopKOption` (line 159)
- variable: `EvalKFactorOption` (line 163)
- variable: `EvalNProbeOption` (line 167)
- variable: `EvalXtrOracleOption` (line 171)
- function: `global_options` (line 181)
- function: `_default_root` (line 186)
- function: `_resolve_root` (line 193)
- function: `_manager` (line 199)
- function: `_build_assets` (line 204)
- function: `_parse_extras` (line 222)
- function: `_parse_sidecars` (line 232)
- function: `_resolve_version_dir` (line 246)
- function: `_manifest_path_for` (line 256)
- function: `_load_manifest` (line 260)
- function: `_write_manifest` (line 269)
- class: `_EmbeddingBuildContext` (line 274)
- function: `_build_context` (line 284)
- function: `_resolve_duck_path` (line 312)
- function: `_resolve_output_path` (line 329)
- function: `_parquet_meta` (line 349)
- function: `_build_embedding_manifest` (line 362)
- function: `_compute_chunk_checksum` (line 388)
- function: `_collect_chunks_and_embeddings` (line 403)
- function: `_deterministic_sample` (line 450)
- function: `_evaluate_drift` (line 484)
- function: `_execute_embeddings_build` (line 509)
- function: `_run_embedding_validation` (line 571)
- function: `_write_embedding_meta` (line 608)
- function: `embeddings_build_command` (line 619)
- function: `embeddings_validate_command` (line 644)
- function: `_parse_tune_overrides` (line 706)
- function: `_faiss_manager` (line 746)
- function: `_duckdb_catalog` (line 759)
- function: `_duckdb_embedding_dim` (line 773)
- function: `_count_idmap_rows` (line 799)
- function: `_load_xtr_index` (line 829)
- function: `_eval_paths` (line 843)
- function: `status_command` (line 853)
- function: `stage_command` (line 863)
- function: `publish_command` (line 920)
- function: `rollback_command` (line 930)
- function: `list_command` (line 940)
- function: `health_command` (line 952)
- function: `export_idmap_command` (line 1011)
- function: `materialize_join_command` (line 1032)
- function: `tune_command` (line 1048)
- function: `tune_params_command` (line 1118)
- function: `show_profile_command` (line 1160)
- function: `_write_tuning_audit` (line 1166)
- function: `_run_autotune` (line 1177)
- function: `eval_command` (line 1203)
- function: `_execute_search` (line 1231)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 12
- **cycle_group**: 86

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 18
- recent churn 90: 18

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
- loc: 1310

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
