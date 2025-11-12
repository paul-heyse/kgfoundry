# plugins/builtins.py

## Docstring

```
Built-in retrieval channel implementations (BM25, SPLADE).
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Sequence
- from **pathlib** import Path
- from **threading** import Lock
- from **codeintel_rev.io.hybrid_search** import BM25Rm3Config, BM25SearchProvider, SpladeSearchProvider
- from **codeintel_rev.plugins.channels** import Channel, ChannelContext, ChannelError
- from **codeintel_rev.retrieval.rm3_heuristics** import RM3Heuristics, RM3Params
- from **codeintel_rev.retrieval.types** import ChannelHit
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 15)
- function: `bm25_factory` (line 20)
- function: `splade_factory` (line 52)
- class: `_BM25Channel` (line 85)
- class: `_SpladeChannel` (line 214)
- function: `_resolve_path` (line 319)
- function: `_classify_skip_reason` (line 326)

## Dependency Graph

- **fan_in**: 0
- **fan_out**: 4
- **cycle_group**: 72

## Declared Exports (__all__)

bm25_factory, splade_factory

## Tags

public-api
