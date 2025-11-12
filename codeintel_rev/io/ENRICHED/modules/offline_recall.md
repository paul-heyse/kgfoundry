# evaluation/offline_recall.py

## Docstring

```
Offline recall evaluator leveraging FAISS + DuckDB catalogs.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **collections.abc** import Iterable, Sequence
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING, cast
- from **(absolute)** import numpy
- from **codeintel_rev.config.settings** import EvalConfig, PathsConfig, Settings
- from **codeintel_rev.io.duckdb_manager** import DuckDBManager
- from **codeintel_rev.io.faiss_manager** import FAISSManager
- from **codeintel_rev.io.symbol_catalog** import SymbolCatalog, SymbolDefRow
- from **codeintel_rev.io.vllm_client** import VLLMClient
- from **codeintel_rev.metrics.registry** import OFFLINE_EVAL_QUERY_COUNT, OFFLINE_EVAL_RECALL_AT_K
- from **kgfoundry_common.logging** import get_logger
- from **codeintel_rev.app.config_context** import ResolvedPaths

## Definitions

- class: `EvalQuery` (line 31)
- class: `OfflineRecallEvaluator` (line 40)
- function: `__init__` (line 43)
- function: `run` (line 59)
- function: `_resolve_output_dir` (line 133)
- function: `_load_queries` (line 141)
- function: `_synthesize_queries` (line 166)
- function: `_build_question` (line 185)
- function: `_embed_query` (line 192)
- function: `_write_artifacts` (line 197)
- function: `_record_metrics` (line 216)
- function: `_prepare_queries` (line 221)
- function: `_evaluate_query` (line 231)

## Tags

overlay-needed
