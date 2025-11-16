# app/faiss_health.py

## Docstring

```
FAISS CPU health checks used during application startup.
```

## Imports

- from **__future__** import annotations
- from **functools** import lru_cache
- from **typing** import Any, cast
- from **codeintel_rev.typing** import gate_import

## Definitions

- function: `_faiss_cpu_smoke` (line 13)
- function: `check_faiss_health` (line 51)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 29

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 1
- recent churn 90: 1

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

check_faiss_health

## Doc Health

- **summary**: FAISS CPU health checks used during application startup.
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

## Config References

- app/hypercorn.toml

## Hotspot

- score: 1.65

## Side Effects

- none detected

## Complexity

- branches: 7
- cyclomatic: 8
- loc: 85

## Doc Coverage

- `_faiss_cpu_smoke` (function): summary=yes, params=ok, examples=no — Run a tiny IndexFlat search to ensure FAISS works on CPU.
- `check_faiss_health` (function): summary=yes, params=ok, examples=no — Perform a FAISS CPU health check and return structured status.

## Tags

low-coverage, public-api
