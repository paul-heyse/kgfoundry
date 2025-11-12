# eval/hybrid_evaluator.py

## Docstring

```
Offline hybrid evaluator with oracle reranking and pool exports.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Sequence
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **(absolute)** import numpy
- from **codeintel_rev.eval.pool_writer** import PoolRow, Source, write_pool
- from **codeintel_rev.io.duckdb_catalog** import DuckDBCatalog
- from **codeintel_rev.io.faiss_manager** import FAISSManager
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 16)
- class: `EvalReport` (line 20)
- class: `HybridPoolEvaluator` (line 29)

## Dependency Graph

- **fan_in**: 2
- **fan_out**: 3
- **cycle_group**: 73

## Declared Exports (__all__)

EvalReport, HybridPoolEvaluator

## Doc Metrics

- **summary**: Offline hybrid evaluator with oracle reranking and pool exports.
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

## Hotspot Score

- score: 1.92

## Side Effects

- filesystem

## Complexity

- branches: 7
- cyclomatic: 8
- loc: 154

## Doc Coverage

- `EvalReport` (class): summary=yes, examples=no — Summary for an offline ANN vs oracle comparison.
- `HybridPoolEvaluator` (class): summary=yes, examples=no — Compare ANN retrieval against a Flat oracle and persist pools.

## Tags

low-coverage, public-api
