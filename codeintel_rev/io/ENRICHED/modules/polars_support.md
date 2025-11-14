# polars_support.py

## Docstring

```
Helpers for optional polars exports.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Callable, Mapping, Sequence
- from **typing** import cast
- from **codeintel_rev.typing** import PolarsDataFrame, PolarsModule

## Definitions

- function: `resolve_polars_frame_factory` (line 15)

## Graph Metrics

- **fan_in**: 2
- **fan_out**: 1
- **cycle_group**: 4

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 2
- recent churn 90: 2

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Helpers for optional polars exports.
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

- score: 1.52

## Side Effects

- none detected

## Complexity

- branches: 2
- cyclomatic: 3
- loc: 48

## Doc Coverage

- `resolve_polars_frame_factory` (function): summary=yes, params=ok, examples=no — Return a DataFrame factory that works across polars versions.

## Tags

low-coverage
