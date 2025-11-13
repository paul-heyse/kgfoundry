# retrieval/boosters.py

## Docstring

```
Score boosters applied after fusion.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import re
- from **(absolute)** import time
- from **collections.abc** import Callable, Iterable, Mapping, Sequence
- from **dataclasses** import dataclass
- from **typing** import TYPE_CHECKING, Any
- from **codeintel_rev.retrieval.types** import HybridResultDoc
- from **(absolute)** import duckdb
- from **codeintel_rev.io.duckdb_manager** import DuckDBManager
- from **codeintel_rev.io.duckdb_manager** import DuckDBManager
- from **duckdb** import DuckDBPyConnection

## Definitions

- variable: `duckdb` (line 16)
- variable: `DuckDBManagerType` (line 21)
- variable: `DuckDBManager` (line 26)
- variable: `DuckConnection` (line 31)
- class: `RecencyConfig` (line 39)
- function: `_now` (line 50)
- function: `_exp_decay` (line 54)
- function: `_safe_identifier` (line 60)
- function: `_normalize_ids` (line 67)
- function: `_create_recency_view` (line 77)
- function: `_populate_id_table` (line 89)
- function: `_fetch_commit_ts_duckdb` (line 94)
- function: `apply_recency_boost` (line 141)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 3
- **cycle_group**: 58

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

RecencyConfig, apply_recency_boost

## Doc Health

- **summary**: Score boosters applied after fusion.
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

- score: 2.21

## Side Effects

- database

## Complexity

- branches: 28
- cyclomatic: 29
- loc: 204

## Doc Coverage

- `RecencyConfig` (class): summary=yes, examples=no — Configuration parameters controlling recency boosts.
- `_now` (function): summary=no, examples=no
- `_exp_decay` (function): summary=no, examples=no
- `_safe_identifier` (function): summary=no, examples=no
- `_normalize_ids` (function): summary=no, examples=no
- `_create_recency_view` (function): summary=no, examples=no
- `_populate_id_table` (function): summary=no, examples=no
- `_fetch_commit_ts_duckdb` (function): summary=no, examples=no
- `apply_recency_boost` (function): summary=yes, params=ok, examples=no — Return a new doc list with an exponential recency boost applied.

## Tags

low-coverage, public-api
