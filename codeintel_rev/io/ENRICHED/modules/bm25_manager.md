# io/bm25_manager.py

## Docstring

```
BM25 indexing workflow helpers.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import importlib
- from **(absolute)** import json
- from **(absolute)** import logging
- from **(absolute)** import shutil
- from **(absolute)** import sys
- from **datetime** import UTC, datetime
- from **hashlib** import sha256
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING
- from **(absolute)** import msgspec
- from **codeintel_rev.io.path_utils** import resolve_within_repo
- from **kgfoundry_common.subprocess_utils** import run_subprocess
- from **codeintel_rev.config.settings** import Settings

## Definitions

- variable: `GENERATOR_NAME` (line 23)
- variable: `CORPUS_METADATA_FILENAME` (line 24)
- variable: `INDEX_METADATA_FILENAME` (line 25)
- variable: `logger` (line 27)
- class: `BM25CorpusMetadata` (line 30)
- class: `BM25CorpusSummary` (line 40)
- class: `BM25IndexMetadata` (line 49)
- class: `BM25BuildOptions` (line 63)
- class: `BM25IndexManager` (line 75)
- function: `_write_struct` (line 307)
- function: `_read_corpus_metadata` (line 314)
- function: `_parse_corpus_line` (line 346)
- function: `_run_pyserini_index` (line 423)
- function: `_detect_pyserini_version` (line 428)
- function: `_directory_size` (line 444)

## Dependency Graph

- **fan_in**: 3
- **fan_out**: 3
- **cycle_group**: 69

## Declared Exports (__all__)

BM25BuildOptions, BM25CorpusMetadata, BM25CorpusSummary, BM25IndexManager, BM25IndexMetadata

## Tags

public-api
