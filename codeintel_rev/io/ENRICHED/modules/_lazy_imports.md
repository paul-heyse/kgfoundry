# _lazy_imports.py

## Docstring

```
Helpers for lazily importing heavy optional dependencies.
```

## Imports

- from **__future__** import annotations
- from **types** import ModuleType
- from **typing** import cast
- from **codeintel_rev.typing** import gate_import

## Definitions

- class: `LazyModule` (line 11)

## Graph Metrics

- **fan_in**: 15
- **fan_out**: 1
- **cycle_group**: 2

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

- **summary**: Helpers for lazily importing heavy optional dependencies.
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

- score: 2.10

## Side Effects

- none detected

## Complexity

- branches: 2
- cyclomatic: 3
- loc: 43

## Doc Coverage

- `LazyModule` (class): summary=yes, examples=no — Proxy object that imports a module only when accessed.

## Tags

low-coverage
