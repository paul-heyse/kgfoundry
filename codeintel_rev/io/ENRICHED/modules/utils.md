# config/utils.py

## Docstring

```
Helpers for working with msgspec-based settings structs.
```

## Imports

- from **__future__** import annotations
- from **msgspec** import Struct, structs
- from **codeintel_rev.config.settings** import Settings

## Definitions

- function: `replace_settings` (line 10)
- function: `replace_struct` (line 45)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 1
- **cycle_group**: 103

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 2
- recent churn 90: 2

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

replace_settings, replace_struct

## Doc Health

- **summary**: Helpers for working with msgspec-based settings structs.
- has summary: yes
- param parity: no
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

- score: 1.03

## Side Effects

- none detected

## Complexity

- branches: 0
- cyclomatic: 1
- loc: 84

## Doc Coverage

- `replace_settings` (function): summary=yes, params=mismatch, examples=no — Return a new Settings instance with updates applied.
- `replace_struct` (function): summary=yes, params=mismatch, examples=no — Clone a struct instance with the provided field overrides applied.

## Tags

low-coverage, public-api
