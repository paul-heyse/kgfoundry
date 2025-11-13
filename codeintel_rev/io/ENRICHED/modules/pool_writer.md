# eval/pool_writer.py

## Docstring

```
Lightweight Parquet writer for evaluator pools.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **collections.abc** import Iterable, Mapping
- from **pathlib** import Path
- from **types** import ModuleType
- from **typing** import TYPE_CHECKING, Literal, Protocol, cast, runtime_checkable
- from **codeintel_rev.retrieval.types** import SearchPoolRow
- from **(absolute)** import pyarrow
- from **(absolute)** import pyarrow.parquet
- from **(absolute)** import pyarrow
- from **(absolute)** import pyarrow.parquet

## Definitions

- variable: `pa` (line 17)
- variable: `pq` (line 18)
- variable: `pa` (line 23)
- variable: `pq` (line 24)
- variable: `pa` (line 26)
- variable: `pq` (line 27)
- variable: `Channel` (line 29)
- class: `_SupportsToList` (line 42)
- function: `_empty_table` (line 48)
- function: `_normalize_meta` (line 84)
- function: `write_pool` (line 122)

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 2
- **cycle_group**: 88

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 7
- recent churn 90: 7

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

- score: 2.11

## Side Effects

- filesystem

## Complexity

- branches: 15
- cyclomatic: 16
- loc: 184

## Doc Coverage

- `_SupportsToList` (class): summary=yes, examples=no — Protocol describing array-like objects exposing ``tolist``.
- `_empty_table` (function): summary=yes, params=ok, examples=no — Return an empty evaluator table with the expected schema.
- `_normalize_meta` (function): summary=yes, params=ok, examples=no — Return a JSON-serialisable copy of ``meta``.
- `write_pool` (function): summary=yes, params=ok, examples=no — Write `(query_id, channel, rank, chunk_id, score, uri, ...)` rows to Parquet.

## Tags

low-coverage, public-api
