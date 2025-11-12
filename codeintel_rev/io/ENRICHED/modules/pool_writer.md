# eval/pool_writer.py

## Docstring

```
Lightweight Parquet writer for evaluator pools.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Iterable
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING, Literal
- from **(absolute)** import pyarrow
- from **(absolute)** import pyarrow.parquet
- from **(absolute)** import pyarrow
- from **(absolute)** import pyarrow.parquet

## Definitions

- variable: `pa` (line 18)
- variable: `pq` (line 19)
- variable: `Source` (line 21)
- class: `PoolRow` (line 25)
- function: `_empty_table` (line 35)
- function: `write_pool` (line 63)

## Dependency Graph

- **fan_in**: 2
- **fan_out**: 1
- **cycle_group**: 72

## Declared Exports (__all__)

PoolRow, write_pool

## Doc Metrics

- **summary**: Lightweight Parquet writer for evaluator pools.
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

- score: 1.79

## Side Effects

- filesystem

## Complexity

- branches: 8
- cyclomatic: 9
- loc: 113

## Doc Coverage

- `PoolRow` (class): summary=yes, examples=no — Single evaluator pool row.
- `_empty_table` (function): summary=yes, params=ok, examples=no — Return an empty evaluator table with the expected schema.
- `write_pool` (function): summary=yes, params=ok, examples=no — Write `(query_id, source, rank, chunk_id, score)` tuples to Parquet.

## Tags

low-coverage, public-api
