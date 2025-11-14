# typedness.py

## Docstring

```
Typedness utilities that build on Pyrefly/Pyright summaries.
```

## Imports

- from **__future__** import annotations
- from **dataclasses** import dataclass
- from **codeintel_rev.enrich.libcst_bridge** import ModuleIndex
- from **codeintel_rev.enrich.type_integration** import TypeSummary, collect_pyrefly, collect_pyright

## Definitions

- class: `FileTypeSignals` (line 13)
- function: `collect_type_signals` (line 25)
- function: `annotation_ratio` (line 67)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 2
- **cycle_group**: 81

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 1
- recent churn 90: 1

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Typedness utilities that build on Pyrefly/Pyright summaries.
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

- score: 1.69

## Side Effects

- none detected

## Complexity

- branches: 5
- cyclomatic: 6
- loc: 85

## Doc Coverage

- `FileTypeSignals` (class): summary=yes, examples=no — Joined Pyrefly/Pyright error counts for a single file.
- `collect_type_signals` (function): summary=yes, params=ok, examples=no — Collect Pyrefly/Pyright diagnostics keyed by file path.
- `annotation_ratio` (function): summary=yes, params=ok, examples=no — Return per-module annotation ratios derived from :class:`ModuleIndex`.

## Tags

low-coverage
