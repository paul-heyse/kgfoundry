# cli/build_indexes.py

## Docstring

```
CLI helpers for building Lucene indexes and flipping lifecycle pointers.
```

## Imports

- from **__future__** import annotations
- from **pathlib** import Path
- from **typing** import Annotated
- from **(absolute)** import typer
- from **codeintel_rev.config.settings** import load_settings
- from **codeintel_rev.indexing.index_lifecycle** import LuceneAssets, link_current_lucene
- from **codeintel_rev.io.bm25_manager** import BM25BuildOptions, BM25IndexManager
- from **codeintel_rev.io.splade_manager** import SpladeBuildOptions, SpladeIndexManager

## Definitions

- function: `_bm25_manager` (line 93)
- function: `_splade_manager` (line 104)
- function: `build_bm25_index` (line 116)
- function: `build_splade_impact_index` (line 142)
- function: `publish_lucene_assets` (line 167)
- function: `main` (line 186)

## Tags

cli, overlay-needed
