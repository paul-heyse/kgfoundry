# io/rrf.py

## Docstring

```
Reciprocal Rank Fusion utilities (legacy compatibility wrappers).
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Mapping, Sequence
- from **typing** import Literal
- from **codeintel_rev.retrieval.fusion** import fuse_weighted_rrf
- from **codeintel_rev.retrieval.types** import ChannelHit

## Definitions

- function: `weighted_rrf` (line 12)
- function: `_normalize_channel_hits` (line 108)
- function: `_to_int` (line 154)

## Dependency Graph

- **fan_in**: 0
- **fan_out**: 3
- **cycle_group**: 80

## Declared Exports (__all__)

weighted_rrf

## Doc Metrics

- **summary**: Reciprocal Rank Fusion utilities (legacy compatibility wrappers).
- has summary: yes
- param parity: yes
- examples present: yes

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Hotspot Score

- score: 1.76

## Side Effects

- none detected

## Complexity

- branches: 7
- cyclomatic: 8
- loc: 163

## Doc Coverage

- `weighted_rrf` (function): summary=yes, params=ok, examples=yes — Apply weighted Reciprocal Rank Fusion to channel hits.
- `_normalize_channel_hits` (function): summary=yes, params=ok, examples=no — Normalize channel hit scores using the specified mode.
- `_to_int` (function): summary=no, examples=no

## Tags

low-coverage, public-api
