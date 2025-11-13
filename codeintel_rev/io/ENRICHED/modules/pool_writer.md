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
- from **types** import ModuleType
- from **typing** import TYPE_CHECKING, Literal, cast
- from **(absolute)** import pyarrow
- from **(absolute)** import pyarrow.parquet
- from **(absolute)** import pyarrow
- from **(absolute)** import pyarrow.parquet

## Definitions

- variable: `pa` (line 15)
- variable: `pq` (line 16)
- variable: `pa` (line 21)
- variable: `pq` (line 22)
- variable: `pa` (line 24)
- variable: `pq` (line 25)
- variable: `Channel` (line 27)
- class: `PoolRow` (line 31)
- function: `_empty_table` (line 45)
- function: `write_pool` (line 87)

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 1
- **cycle_group**: 87

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 6
- recent churn 90: 6

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

- score: 1.88

## Side Effects

- filesystem

## Complexity

- branches: 8
- cyclomatic: 9
- loc: 160

## Doc Coverage

- `PoolRow` (class): summary=yes, examples=no — Single evaluator pool row.
- `_empty_table` (function): summary=yes, params=ok, examples=no — Return an empty evaluator table with the expected schema.
- `write_pool` (function): summary=yes, params=ok, examples=no — Write `(query_id, channel, rank, chunk_id, score, uri, ...)` rows to Parquet.

## Tags

low-coverage, public-api
