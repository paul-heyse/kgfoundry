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
- function: `_build_xtr_config` (line 210)
- function: `_build_rerank_config` (line 226)
- class: `CodeRankConfig` (line 237)
- class: `WarpConfig` (line 276)
- class: `XTRConfig` (line 303)
- class: `RerankConfig` (line 316)
- class: `EvalConfig` (line 325)
- class: `CodeRankLLMConfig` (line 337)
- class: `VLLMRunMode` (line 349)
- class: `VLLMConfig` (line 355)
- class: `BM25Config` (line 422)
- class: `PRFConfig` (line 439)
- class: `SpladeConfig` (line 451)
- class: `PathsConfig` (line 519)
- class: `IndexConfig` (line 592)
- class: `ServerLimits` (line 666)
- class: `RedisConfig` (line 712)
- class: `Settings` (line 733)
- function: `load_settings` (line 798)
- function: `_build_paths_config` (line 1034)
- function: `_load_rrf_weights` (line 1055)
- function: `_load_hybrid_prefetch` (line 1076)
- function: `_load_hybrid_weights_override` (line 1097)
- function: `_build_prf_config` (line 1116)
- function: `_load_hybrid_channel_settings` (line 1128)
- function: `_build_index_config` (line 1137)
- function: `_build_server_limits` (line 1177)
- function: `_build_redis_config` (line 1187)
- function: `_build_duckdb_config` (line 1201)
- function: `_build_eval_config` (line 1217)
- function: `_resolve_bm25_analyzer` (line 1229)
- function: `_resolve_splade_analyzer` (line 1236)
- function: `_build_bm25_config` (line 1243)
- function: `_build_splade_config` (line 1274)
- function: `_build_coderank_config` (line 1297)
- function: `_build_warp_config` (line 1315)
- function: `_build_coderank_llm_config` (line 1326)

## Graph Metrics

- **fan_in**: 22
- **fan_out**: 2
- **cycle_group**: 46

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 27
- recent churn 90: 27

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

BM25Config, CodeRankConfig, CodeRankLLMConfig, IndexConfig, PRFConfig, PathsConfig, RedisConfig, RerankConfig, ServerLimits, Settings, SpladeConfig, VLLMConfig, VLLMRunMode, WarpConfig, XTRConfig, load_settings

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

- score: 2.99

## Side Effects

- filesystem

## Complexity

- branches: 45
- cyclomatic: 46
- loc: 1356

## Doc Coverage

- `_HybridChannelSettings` (class): summary=no, examples=no
- `_env_bool` (function): summary=yes, params=ok, examples=no — Return a boolean flag parsed from environment variables.
- `_parse_int_with_suffix` (function): summary=yes, params=ok, examples=no — Return an integer, accepting 1k-style suffixes (k=1_000).
- `_parse_int_list` (function): summary=yes, params=ok, examples=no — Return a tuple of integers from a comma-separated configuration string.
- `_optional_int` (function): summary=yes, params=ok, examples=no — Convert an optional string to ``int`` when possible.
- `_build_vllm_config` (function): summary=no, examples=no
- `_build_xtr_config` (function): summary=no, examples=no
- `_build_rerank_config` (function): summary=no, examples=no
- `CodeRankConfig` (class): summary=yes, examples=no — Configuration for the CodeRank dense retriever.
- `WarpConfig` (class): summary=yes, examples=no — Configuration for the WARP/XTR late-interaction reranker.

## Tags

low-coverage, public-api, reexport-hub
