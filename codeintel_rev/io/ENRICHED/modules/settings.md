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
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import Literal
- from **(absolute)** import msgspec
- from **codeintel_rev.io.duckdb_manager** import DuckDBConfig

## Definitions

- variable: `DEFAULT_RRF_WEIGHTS` (line 19)
- class: `_HybridChannelSettings` (line 28)
- function: `_env_bool` (line 35)
- function: `_parse_int_with_suffix` (line 55)
- function: `_parse_int_list` (line 99)
- function: `_optional_int` (line 145)
- function: `_build_vllm_config` (line 182)
- function: `_build_embeddings_config` (line 210)
- function: `_build_xtr_config` (line 247)
- function: `_build_rerank_config` (line 263)
- class: `CodeRankConfig` (line 274)
- class: `WarpConfig` (line 313)
- class: `XTRConfig` (line 340)
- class: `RerankConfig` (line 353)
- class: `EvalConfig` (line 362)
- class: `CodeRankLLMConfig` (line 374)
- class: `VLLMRunMode` (line 386)
- class: `VLLMConfig` (line 392)
- class: `EmbeddingsConfig` (line 460)
- class: `BM25Config` (line 512)
- class: `PRFConfig` (line 529)
- class: `SpladeConfig` (line 541)
- class: `PathsConfig` (line 609)
- class: `IndexConfig` (line 682)
- class: `ServerLimits` (line 756)
- class: `RedisConfig` (line 802)
- class: `Settings` (line 823)
- function: `load_settings` (line 893)
- function: `_build_paths_config` (line 1131)
- function: `_load_rrf_weights` (line 1152)
- function: `_load_hybrid_prefetch` (line 1173)
- function: `_load_hybrid_weights_override` (line 1194)
- function: `_build_prf_config` (line 1213)
- function: `_load_hybrid_channel_settings` (line 1225)
- function: `_build_index_config` (line 1234)
- function: `_build_server_limits` (line 1274)
- function: `_build_redis_config` (line 1284)
- function: `_build_duckdb_config` (line 1298)
- function: `_build_eval_config` (line 1314)
- function: `_resolve_bm25_analyzer` (line 1326)
- function: `_resolve_splade_analyzer` (line 1333)
- function: `_build_bm25_config` (line 1340)
- function: `_build_splade_config` (line 1371)
- function: `_build_coderank_config` (line 1394)
- function: `_build_warp_config` (line 1412)
- function: `_build_coderank_llm_config` (line 1423)

## Graph Metrics

- **fan_in**: 25
- **fan_out**: 2
- **cycle_group**: 18

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 28
- recent churn 90: 28

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

BM25Config, CodeRankConfig, CodeRankLLMConfig, EmbeddingsConfig, IndexConfig, PRFConfig, PathsConfig, RedisConfig, RerankConfig, ServerLimits, Settings, SpladeConfig, VLLMConfig, VLLMRunMode, WarpConfig, XTRConfig, load_settings

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

- score: 3.05

## Side Effects

- filesystem

## Complexity

- branches: 47
- cyclomatic: 48
- loc: 1454

## Doc Coverage

- `_HybridChannelSettings` (class): summary=no, examples=no
- `_env_bool` (function): summary=yes, params=ok, examples=no — Return a boolean flag parsed from environment variables.
- `_parse_int_with_suffix` (function): summary=yes, params=ok, examples=no — Return an integer, accepting 1k-style suffixes (k=1_000).
- `_parse_int_list` (function): summary=yes, params=ok, examples=no — Return a tuple of integers from a comma-separated configuration string.
- `_optional_int` (function): summary=yes, params=ok, examples=no — Convert an optional string to ``int`` when possible.
- `_build_vllm_config` (function): summary=no, examples=no
- `_build_embeddings_config` (function): summary=no, examples=no
- `_build_xtr_config` (function): summary=no, examples=no
- `_build_rerank_config` (function): summary=no, examples=no
- `CodeRankConfig` (class): summary=yes, examples=no — Configuration for the CodeRank dense retriever.

## Tags

low-coverage, public-api, reexport-hub
