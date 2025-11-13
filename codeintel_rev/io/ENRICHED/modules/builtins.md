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
- from **codeintel_rev.retrieval.types** import SearchHit
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 15)
- function: `bm25_factory` (line 20)
- function: `splade_factory` (line 52)
- class: `_BM25Channel` (line 85)
- class: `_SpladeChannel` (line 214)
- function: `_resolve_path` (line 319)
- function: `_classify_skip_reason` (line 326)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 4
- **cycle_group**: 118

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 6
- recent churn 90: 6

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

bm25_factory, splade_factory

## Doc Health

- **summary**: Built-in retrieval channel implementations (BM25, SPLADE).
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

- score: 2.19

## Side Effects

- filesystem

## Complexity

- branches: 26
- cyclomatic: 27
- loc: 333

## Doc Coverage

- `bm25_factory` (function): summary=yes, params=ok, examples=no — Return the built-in BM25 channel.
- `splade_factory` (function): summary=yes, params=ok, examples=no — Return the built-in SPLADE impact channel.
- `_BM25Channel` (class): summary=no, examples=no
- `_SpladeChannel` (class): summary=no, examples=no
- `_resolve_path` (function): summary=no, examples=no
- `_classify_skip_reason` (function): summary=no, examples=no

## Tags

low-coverage, public-api
