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

- function: `bm25_factory` (line 20)
- function: `splade_factory` (line 52)
- class: `_BM25Channel` (line 85)
- function: `__init__` (line 90)
- function: `search` (line 99)
- function: `_ensure_provider` (line 154)
- class: `_SpladeChannel` (line 214)
- function: `__init__` (line 219)
- function: `search` (line 228)
- function: `_ensure_provider` (line 285)
- function: `_resolve_path` (line 319)
- function: `_classify_skip_reason` (line 326)

## Tags

overlay-needed, public-api
