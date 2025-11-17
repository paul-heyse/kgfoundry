# io/faiss_compat.py

## Docstring

```
Compatibility helpers for importing FAISS safely on Python 3.13+.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import sys
- from **(absolute)** import warnings
- from **collections.abc** import Iterator
- from **types** import ModuleType
- from **codeintel_rev.typing** import gate_import

## Definitions

- function: `load_faiss_module` (line 15)
- function: `sanitize_faiss_bindings` (line 46)
- function: `_iter_faiss_modules` (line 64)
- function: `_assign_missing_module_attr` (line 72)

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 1
- **cycle_group**: 4

## Ownership

- bus factor: 0.00
- recent churn 30: 0
- recent churn 90: 0

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Compatibility helpers for importing FAISS safely on Python 3.13+.
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

- score: 1.94

## Side Effects

- none detected

## Complexity

- branches: 10
- cyclomatic: 11
- loc: 82

## Doc Coverage

- `load_faiss_module` (function): summary=yes, params=ok, examples=no — Import FAISS and sanitize SWIG-generated types.
- `sanitize_faiss_bindings` (function): summary=yes, params=ok, examples=no — Ensure SWIG-created types report their defining module.
- `_iter_faiss_modules` (function): summary=no, examples=no
- `_assign_missing_module_attr` (function): summary=no, examples=no

## Tags

low-coverage
