# eval/hybrid_evaluator.py

## Docstring

```
Offline hybrid evaluator with oracle reranking and pool exports.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **collections.abc** import Sequence
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING
- from **(absolute)** import numpy
- from **codeintel_rev.eval.pool_writer** import PoolRow, Source, write_pool
- from **codeintel_rev.io.duckdb_catalog** import DuckDBCatalog
- from **codeintel_rev.io.faiss_manager** import FAISSManager
- from **kgfoundry_common.logging** import get_logger
- from **codeintel_rev.io.xtr_manager** import XTRIndex

## Definitions

- variable: `XTRIndex` (line 21)
- variable: `LOGGER` (line 23)
- class: `EvalConfig` (line 27)
- class: `EvalReport` (line 40)
- class: `_EvalState` (line 54)
- class: `HybridPoolEvaluator` (line 64)

## Graph Metrics

- **fan_in**: 2
- **fan_out**: 5
- **cycle_group**: 78

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 4
- recent churn 90: 4

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

EvalConfig, EvalReport, HybridPoolEvaluator

## Doc Health

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

## Hotspot

- score: 2.32

## Side Effects

- filesystem

## Complexity

- branches: 21
- cyclomatic: 22
- loc: 297

## Doc Coverage

- `EvalConfig` (class): summary=yes, examples=no — Evaluator configuration.
- `EvalReport` (class): summary=yes, examples=no — Summary for an offline ANN vs oracle comparison.
- `_EvalState` (class): summary=no, examples=no
- `HybridPoolEvaluator` (class): summary=yes, examples=no — Compare ANN retrieval against Flat and optional XTR oracles, persisting pools.

## Tags

low-coverage, public-api
