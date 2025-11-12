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
- **cycle_group**: 64

## Declared Exports (__all__)

weighted_rrf

## Tags

public-api
