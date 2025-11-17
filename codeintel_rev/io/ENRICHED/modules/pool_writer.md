# eval/pool_writer.py

## Docstring

```
Lightweight Parquet writer for evaluator pools.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Iterable, Sequence
- from **pathlib** import Path
- from **types** import ModuleType
- from **typing** import TYPE_CHECKING, Literal, cast
- from **codeintel_rev.retrieval.types** import SearchPoolRow
- from **(absolute)** import pyarrow
- from **(absolute)** import pyarrow.parquet
- from **(absolute)** import pyarrow
- from **(absolute)** import pyarrow.parquet

## Definitions

- variable: `pa` (line 16)
- variable: `pq` (line 17)
- variable: `pa` (line 22)
- variable: `pq` (line 23)
- variable: `pa` (line 25)
- variable: `pq` (line 26)
- variable: `Channel` (line 28)
- function: `_coerce_str_sequence` (line 40)
- function: `_empty_table` (line 64)
- function: `write_pool` (line 111)

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 2
- **cycle_group**: 84

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 13
- recent churn 90: 13

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

Channel, SearchPoolRow, write_pool

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

- score: 2.13

## Side Effects

- filesystem

## Complexity

- branches: 16
- cyclomatic: 17
- loc: 193

## Doc Coverage

- `_coerce_str_sequence` (function): summary=yes, params=ok, examples=no — Return a normalized list of strings for any iterable payload.
- `_empty_table` (function): summary=yes, params=ok, examples=no — Return an empty evaluator table with the expected schema.
- `write_pool` (function): summary=yes, params=ok, examples=no — Write `(query_id, channel, rank, chunk_id, score, uri, ...)` rows to Parquet.

## Tags

low-coverage, public-api
