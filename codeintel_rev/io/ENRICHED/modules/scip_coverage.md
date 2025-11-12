# evaluation/scip_coverage.py

## Docstring

```
SCIP symbol coverage evaluator.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **collections.abc** import Sequence
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import Protocol, TypedDict
- from **(absolute)** import numpy
- from **codeintel_rev.config.settings** import Settings
- from **codeintel_rev.io.duckdb_manager** import DuckDBManager
- from **codeintel_rev.io.faiss_manager** import SearchRuntimeOverrides
- from **codeintel_rev.io.symbol_catalog** import SymbolCatalog, SymbolDefRow
- from **codeintel_rev.metrics.registry** import SCIP_CHUNK_COVERAGE_RATIO, SCIP_INDEX_COVERAGE_RATIO, SCIP_RETRIEVAL_COVERAGE_RATIO
- from **kgfoundry_common.logging** import get_logger

## Definitions

- class: `SupportsFaissSearch` (line 27)
- function: `search` (line 30)
- class: `SupportsEmbedSingle` (line 42)
- function: `embed_single` (line 45)
- class: `CoverageResult` (line 51)
- class: `CoverageSummary` (line 61)
- class: `SCIPCoverageEvaluator` (line 71)
- function: `__init__` (line 74)
- function: `run` (line 90)
- function: `_lookup_chunk_ids` (line 178)
- function: `_embed` (line 193)
- function: `_question_for` (line 198)
- function: `_record_metrics` (line 206)
- function: `_write_artifacts` (line 211)
- function: `_evaluate_symbol` (line 238)

## Tags

overlay-needed
