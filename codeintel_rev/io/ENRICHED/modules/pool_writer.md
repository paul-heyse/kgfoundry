# eval/pool_writer.py

## Docstring

```
Lightweight Parquet writer for evaluator pools.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **collections.abc** import Iterable, Mapping
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING, Literal
- from **(absolute)** import pyarrow
- from **(absolute)** import pyarrow.parquet
- from **(absolute)** import pyarrow
- from **(absolute)** import pyarrow.parquet

## Definitions

- variable: `pa` (line 19)
- variable: `pq` (line 20)
- variable: `Source` (line 22)
- class: `PoolRow` (line 26)
- function: `_empty_table` (line 40)
- function: `write_pool` (line 82)

## Graph Metrics

- **fan_in**: 2
- **fan_out**: 1
- **cycle_group**: 77

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 5
- recent churn 90: 5

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

PoolRow, write_pool

## Doc Health

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

## Hotspot

- score: 1.82

## Side Effects

- filesystem

## Complexity

- branches: 9
- cyclomatic: 10
- loc: 163

## Doc Coverage

- `PoolRow` (class): summary=yes, examples=no — Single evaluator pool row.
- `_empty_table` (function): summary=yes, params=ok, examples=no — Return an empty evaluator table with the expected schema.
- `write_pool` (function): summary=yes, params=ok, examples=no — Write `(query_id, source, rank, chunk_id, score)` tuples to Parquet.

## Tags

low-coverage, public-api
