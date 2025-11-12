# retrieval/rm3_heuristics.py

## Docstring

```
Heuristics for toggling RM3 pseudo-relevance feedback per query.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import re
- from **collections.abc** import Iterable
- from **dataclasses** import dataclass

## Definitions

- class: `RM3Params` (line 13)
- class: `RM3Heuristics` (line 21)

## Dependency Graph

- **fan_in**: 2
- **fan_out**: 0
- **cycle_group**: 56

## Declared Exports (__all__)

RM3Heuristics, RM3Params

## Doc Metrics

- **summary**: Heuristics for toggling RM3 pseudo-relevance feedback per query.
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

## Hotspot Score

- score: 1.65

## Side Effects

- none detected

## Complexity

- branches: 7
- cyclomatic: 8
- loc: 124

## Doc Coverage

- `RM3Params` (class): summary=yes, examples=no — Default RM3 parameters used when pseudo-relevance feedback is enabled.
- `RM3Heuristics` (class): summary=yes, examples=no — Lightweight heuristics to decide when RM3 should be enabled for a query.

## Tags

low-coverage, public-api
