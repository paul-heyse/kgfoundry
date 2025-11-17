# config/settings.py

## Docstring

```
Configuration settings using msgspec for fast, validated config.

NO Pydantic - using msgspec.Struct for performance-critical settings.
All configuration loaded from environment variables with sensible defaults.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **(absolute)** import os
- from **(absolute)** import warnings
- from **dataclasses** import dataclass
- from **enum** import StrEnum
- from **functools** import cache
- from **pathlib** import Path
- from **typing** import Literal, TypedDict, cast
- from **(absolute)** import msgspec
- from **codeintel_rev.io.duckdb_manager** import DuckDBConfig

## Definitions

- variable: `DEFAULT_RRF_WEIGHTS` (line 22)
- function: `_emit_vllm_task_warning` (line 30)
- function: `_warn_vllm_task_deprecated` (line 39)
- class: `_HybridChannelSettings` (line 45)
- function: `_env_bool` (line 52)
- function: `_parse_int_with_suffix` (line 72)
- function: `_parse_int_list` (line 116)
- function: `_optional_int` (line 162)
- function: `_build_vllm_config` (line 199)
- function: `_build_embeddings_config` (line 230)
- function: `_build_xtr_config` (line 267)
- function: `_build_rerank_config` (line 283)
- class: `CodeRankConfig` (line 294)
- class: `WarpConfig` (line 333)
- class: `XTRConfig` (line 360)
- class: `RerankConfig` (line 373)
- class: `EvalConfig` (line 382)
- class: `CodeRankLLMConfig` (line 394)
- class: `VLLMRunMode` (line 406)
- class: `VLLMEmbeddingMode` (line 412)
- class: `PoolerConfigKwargs` (line 469)
- class: `VLLMConfig` (line 476)
- class: `EmbeddingsConfig` (line 584)
- class: `BM25Config` (line 636)
- class: `PRFConfig` (line 653)
- class: `SpladeConfig` (line 665)
- class: `PathsConfig` (line 733)
- class: `IndexConfig` (line 806)
- class: `ServerLimits` (line 876)
- class: `RedisConfig` (line 922)
- class: `Settings` (line 943)
- function: `load_settings` (line 1013)
- function: `_build_paths_config` (line 1249)
- function: `_load_rrf_weights` (line 1270)
- function: `_load_hybrid_prefetch` (line 1291)
- function: `_load_hybrid_weights_override` (line 1312)
- function: `_build_prf_config` (line 1331)
- function: `_load_hybrid_channel_settings` (line 1343)
- function: `_build_index_config` (line 1352)
- function: `_build_server_limits` (line 1391)
- function: `_build_redis_config` (line 1401)
- function: `_build_duckdb_config` (line 1415)
- function: `_build_eval_config` (line 1431)
- function: `_resolve_bm25_analyzer` (line 1443)
- function: `_resolve_splade_analyzer` (line 1450)
- function: `_build_bm25_config` (line 1457)
- function: `_build_splade_config` (line 1488)
- function: `_build_coderank_config` (line 1511)
- function: `_build_warp_config` (line 1529)
- function: `_build_coderank_llm_config` (line 1540)

## Graph Metrics

- **fan_in**: 24
- **fan_out**: 2
- **cycle_group**: 9

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 33
- recent churn 90: 33

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

BM25Config, CodeRankConfig, CodeRankLLMConfig, EmbeddingsConfig, IndexConfig, PRFConfig, PathsConfig, RedisConfig, RerankConfig, ServerLimits, Settings, SpladeConfig, VLLMConfig, VLLMEmbeddingMode, VLLMRunMode, WarpConfig, XTRConfig, load_settings

## Doc Health

- **summary**: Configuration settings using msgspec for fast, validated config.
- has summary: yes
- param parity: yes
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

- score: 3.06

## Side Effects

- filesystem

## Complexity

- branches: 51
- cyclomatic: 52
- loc: 1572

## Doc Coverage

- `_emit_vllm_task_warning` (function): summary=yes, params=ok, examples=no — Emit a deprecation warning exactly once.
- `_warn_vllm_task_deprecated` (function): summary=yes, params=mismatch, examples=no — Proxy helper preserving the previous call signature.
- `_HybridChannelSettings` (class): summary=no, examples=no
- `_env_bool` (function): summary=yes, params=ok, examples=no — Return a boolean flag parsed from environment variables.
- `_parse_int_with_suffix` (function): summary=yes, params=ok, examples=no — Return an integer, accepting 1k-style suffixes (k=1_000).
- `_parse_int_list` (function): summary=yes, params=ok, examples=no — Return a tuple of integers from a comma-separated configuration string.
- `_optional_int` (function): summary=yes, params=ok, examples=no — Convert an optional string to ``int`` when possible.
- `_build_vllm_config` (function): summary=no, examples=no
- `_build_embeddings_config` (function): summary=no, examples=no
- `_build_xtr_config` (function): summary=no, examples=no

## Tags

low-coverage, public-api, reexport-hub
