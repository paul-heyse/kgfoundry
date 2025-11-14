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

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 6
- **cycle_group**: 96

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 4
- recent churn 90: 4

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: SCIP symbol coverage evaluator.
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

- score: 2.26

## Side Effects

- filesystem

## Complexity

- branches: 17
- cyclomatic: 18
- loc: 261

## Doc Coverage

- `SupportsFaissSearch` (class): summary=yes, examples=no — Protocol capturing the subset of FAISS search methods required here.
- `SupportsEmbedSingle` (class): summary=yes, examples=no — Protocol describing embedder behaviour used by the evaluator.
- `CoverageResult` (class): summary=yes, examples=no — Container for per-symbol coverage evaluation.
- `CoverageSummary` (class): summary=yes, examples=no — Typed summary payload returned by ``SCIPCoverageEvaluator``.
- `SCIPCoverageEvaluator` (class): summary=yes, examples=no — Evaluate chunk/index/retrieval coverage across SCIP function definitions.

## Tags

low-coverage
