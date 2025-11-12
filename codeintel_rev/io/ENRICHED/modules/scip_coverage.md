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

- variable: `LOGGER` (line 24)
- class: `SupportsFaissSearch` (line 27)
- class: `SupportsEmbedSingle` (line 42)
- class: `CoverageResult` (line 51)
- class: `CoverageSummary` (line 61)
- class: `SCIPCoverageEvaluator` (line 71)

## Dependency Graph

- **fan_in**: 1
- **fan_out**: 6
- **cycle_group**: 53
