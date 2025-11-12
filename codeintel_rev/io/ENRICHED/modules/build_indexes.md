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

- variable: `JsonDirOption` (line 15)
- variable: `IndexDirOption` (line 23)
- variable: `VectorsDirOption` (line 31)
- variable: `ThreadsOption` (line 39)
- variable: `MaxClauseOption` (line 48)
- variable: `OverwriteFlag` (line 57)
- variable: `VersionArgument` (line 65)
- variable: `BaseDirOption` (line 69)
- variable: `Bm25DirOption` (line 77)
- variable: `SpladeDirOption` (line 81)
- variable: `app` (line 86)
- function: `_bm25_manager` (line 93)
- function: `_splade_manager` (line 104)
- function: `build_bm25_index` (line 116)
- function: `build_splade_impact_index` (line 142)
- function: `publish_lucene_assets` (line 167)
- function: `main` (line 186)

## Dependency Graph

- **fan_in**: 0
- **fan_out**: 5
- **cycle_group**: 86

## Tags

cli
