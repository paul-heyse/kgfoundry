# diagnostics/detectors.py

## Docstring

```
Lightweight heuristics over run reports to surface diagnostics hints.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Mapping, Sequence
- from **typing** import Any

## Definitions

- variable: `StageRecord` (line 8)
- function: `_stage_by_prefix` (line 15)
- function: `_stage_attr` (line 23)
- function: `_collect_mapping` (line 32)
- function: `_collect_stages` (line 39)
- function: `_gap_hint` (line 46)
- function: `_sparse_hint` (line 56)
- function: `_vllm_hints` (line 66)
- function: `_faiss_hint` (line 90)
- function: `_rrf_hint` (line 106)
- function: `detect` (line 123)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 34

## Ownership

- bus factor: 0.00
- recent churn 30: 0
- recent churn 90: 0

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

detect

## Doc Health

- **summary**: Lightweight heuristics over run reports to surface diagnostics hints.
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

- score: 2.02

## Side Effects

- none detected

## Complexity

- branches: 29
- cyclomatic: 30
- loc: 166

## Doc Coverage

- `_stage_by_prefix` (function): summary=no, examples=no
- `_stage_attr` (function): summary=no, examples=no
- `_collect_mapping` (function): summary=no, examples=no
- `_collect_stages` (function): summary=no, examples=no
- `_gap_hint` (function): summary=no, examples=no
- `_sparse_hint` (function): summary=no, examples=no
- `_vllm_hints` (function): summary=no, examples=no
- `_faiss_hint` (function): summary=no, examples=no
- `_rrf_hint` (function): summary=no, examples=no
- `detect` (function): summary=yes, params=ok, examples=no — Return structured hints derived from the run report payload.

## Tags

low-coverage, public-api
