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
- **cycle_group**: 107

## Doc Metrics

- **summary**: CLI helpers for building Lucene indexes and flipping lifecycle pointers.
- has summary: yes
- param parity: no
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

- score: 1.85

## Side Effects

- filesystem

## Complexity

- branches: 5
- cyclomatic: 6
- loc: 193

## Doc Coverage

- `_bm25_manager` (function): summary=yes, params=ok, examples=no — Return a BM25 index manager configured from the active settings.
- `_splade_manager` (function): summary=yes, params=ok, examples=no — Return a SPLADE index manager configured from the active settings.
- `build_bm25_index` (function): summary=yes, params=mismatch, examples=no — Build a Lucene BM25 index with positional/docvector/raw storage enabled.
- `build_splade_impact_index` (function): summary=yes, params=mismatch, examples=no — Build a SPLADE Lucene impact index from JsonVectorCollection shards.
- `publish_lucene_assets` (function): summary=yes, params=mismatch, examples=no — Copy Lucene assets into the lifecycle root and flip the CURRENT pointer.
- `main` (function): summary=yes, params=ok, examples=no — Execute the build_indexes CLI.

## Tags

low-coverage
