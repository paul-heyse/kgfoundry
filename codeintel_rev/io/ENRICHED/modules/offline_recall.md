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
- from **typing** import TYPE_CHECKING
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

- variable: `LOGGER` (line 27)
- class: `EvalQuery` (line 31)
- class: `OfflineRecallEvaluator` (line 40)

## Dependency Graph

- **fan_in**: 2
- **fan_out**: 8
- **cycle_group**: 42
