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
- from **typing** import Literal, cast
- from **(absolute)** import msgspec
- from **codeintel_rev.io.duckdb_manager** import DuckDBConfig

## Definitions

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
- class: `IndexConfig` (line 587)
- function: `__post_init__` (line 653)
- class: `ServerLimits` (line 661)
- class: `RedisConfig` (line 707)
- class: `Settings` (line 728)
- function: `load_settings` (line 793)
- function: `_build_paths_config` (line 1027)
- function: `_load_rrf_weights` (line 1047)
- function: `_load_hybrid_prefetch` (line 1068)
- function: `_load_hybrid_weights_override` (line 1089)
- function: `_build_prf_config` (line 1108)
- function: `_load_hybrid_channel_settings` (line 1120)
- function: `_build_index_config` (line 1129)
- function: `_build_server_limits` (line 1169)
- function: `_build_redis_config` (line 1179)
- function: `_build_duckdb_config` (line 1193)
- function: `_build_eval_config` (line 1209)
- function: `_resolve_bm25_analyzer` (line 1221)
- function: `_resolve_splade_analyzer` (line 1228)
- function: `_build_bm25_config` (line 1235)
- function: `_build_splade_config` (line 1266)
- function: `_build_coderank_config` (line 1289)
- function: `_build_warp_config` (line 1307)
- function: `_build_coderank_llm_config` (line 1318)

## Tags

overlay-needed, public-api, reexport-hub
