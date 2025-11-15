# indexing/chunk_ids.py

## Docstring

```
Deterministic chunk identifier helpers.
```

## Imports

- from **__future__** import annotations
- from **hashlib** import blake2b

## Definitions

- function: `stable_chunk_id` (line 12)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 0
- **cycle_group**: 36

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

stable_chunk_id

## Doc Health

- **summary**: Deterministic chunk identifier helpers.
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

- score: 1.24

## Side Effects

- none detected

## Complexity

- branches: 2
- cyclomatic: 3
- loc: 53

## Doc Coverage

- `stable_chunk_id` (function): summary=yes, params=ok, examples=no — Return a deterministic signed 64-bit chunk identifier.

## Tags

low-coverage, public-api
