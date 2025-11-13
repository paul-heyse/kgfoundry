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
- from **codeintel_rev.io.faiss_manager** import FAISSManager
- from **codeintel_rev.io.parquet_store** import ParquetWriteOptions, extract_embeddings, read_chunks_parquet, write_chunks_parquet
- from **codeintel_rev.io.xtr_manager** import XTRIndex
- from **codeintel_rev.typing** import NDArrayF32
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 43)
- variable: `app` (line 44)
- variable: `DEFAULT_XTR_ORACLE` (line 45)
- variable: `embeddings_app` (line 46)
- function: `_get_settings` (line 51)
- variable: `RootOption` (line 62)
- variable: `ExtraOption` (line 63)
- variable: `VersionArg` (line 71)
- variable: `PathArg` (line 72)
- variable: `IndexOption` (line 73)
- variable: `AssetsArg` (line 74)
- variable: `SidecarOption` (line 82)
- variable: `VersionOption` (line 90)
- variable: `ParquetOption` (line 94)
- variable: `OutputOption` (line 97)
- variable: `ChunkBatchOption` (line 98)
- variable: `SampleOption` (line 102)
- variable: `EpsilonOption` (line 103)
- variable: `SweepMode` (line 107)
- variable: `SWEEP_OPTION` (line 120)
- variable: `IdMapOption` (line 125)
- variable: `DuckOption` (line 126)
- variable: `OutOption` (line 127)
- variable: `ParamSpaceArg` (line 128)
- variable: `EvalTopKOption` (line 132)
- variable: `EvalKFactorOption` (line 136)
- variable: `EvalNProbeOption` (line 140)
- variable: `EvalXtrOracleOption` (line 144)
- function: `global_options` (line 154)
- function: `_default_root` (line 159)
- function: `_resolve_root` (line 166)
- function: `_manager` (line 172)
- function: `_build_assets` (line 177)
- function: `_parse_extras` (line 195)
- function: `_parse_sidecars` (line 206)
- function: `_resolve_version_dir` (line 225)
- function: `_manifest_path_for` (line 235)
- function: `_load_manifest` (line 239)
- function: `_write_manifest` (line 249)
- class: `_EmbeddingBuildContext` (line 254)
- function: `_build_context` (line 264)
- function: `_resolve_duck_path` (line 292)
- function: `_resolve_output_path` (line 309)
- function: `_parquet_meta` (line 329)
- function: `_build_embedding_manifest` (line 342)
- function: `_compute_chunk_checksum` (line 368)
- function: `_collect_chunks_and_embeddings` (line 383)
- function: `_deterministic_sample` (line 430)
- function: `_evaluate_drift` (line 464)
- function: `_execute_embeddings_build` (line 489)
- function: `_run_embedding_validation` (line 551)
- function: `_write_embedding_meta` (line 588)
- function: `embeddings_build_command` (line 603)
- function: `embeddings_validate_command` (line 628)
- function: `_parse_tune_overrides` (line 690)
- function: `_faiss_manager` (line 730)
- function: `_duckdb_catalog` (line 744)
- function: `_load_xtr_index` (line 758)
- function: `_eval_paths` (line 774)
- function: `status_command` (line 784)
- function: `stage_command` (line 794)
- function: `publish_command` (line 851)
- function: `rollback_command` (line 861)
- function: `list_command` (line 871)
- function: `export_idmap_command` (line 883)
- function: `materialize_join_command` (line 906)
- function: `tune_command` (line 922)
- function: `tune_params_command` (line 992)
- function: `show_profile_command` (line 1034)
- function: `_write_tuning_audit` (line 1040)
- function: `_run_autotune` (line 1051)
- function: `eval_command` (line 1077)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 12
- **cycle_group**: 129

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 11
- recent churn 90: 11

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

- score: 2.90

## Side Effects

- filesystem

## Complexity

- branches: 83
- cyclomatic: 84
- loc: 1108

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
