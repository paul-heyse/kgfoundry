# coverage_ingest.py

## Docstring

```
Coverage ingestion utilities (Cobertura-style XML).
```

## Imports

- from **__future__** import annotations
- from **pathlib** import Path
- from **defusedxml** import ElementTree
- from **xml.etree** import ElementTree

## Definitions

- function: `collect_coverage` (line 15)
- function: `_parse_int` (line 60)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 0
- **cycle_group**: 16

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 5
- recent churn 90: 5

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Coverage ingestion utilities (Cobertura-style XML).
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

- score: 1.54

## Side Effects

- filesystem

## Complexity

- branches: 9
- cyclomatic: 10
- loc: 79

## Doc Coverage

- `collect_coverage` (function): summary=yes, params=ok, examples=no — Collect per-file coverage ratios from ``coverage.xml``.
- `_parse_int` (function): summary=yes, params=ok, examples=no — Return integer conversion fallback to zero on failure.

## Tags

low-coverage
