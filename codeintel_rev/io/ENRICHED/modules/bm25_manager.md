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

- class: `BM25CorpusMetadata` (line 30)
- class: `BM25CorpusSummary` (line 40)
- class: `BM25IndexMetadata` (line 49)
- class: `BM25BuildOptions` (line 63)
- class: `BM25IndexManager` (line 75)
- function: `__init__` (line 78)
- function: `corpus_dir` (line 85)
- function: `index_dir` (line 90)
- function: `prepare_corpus` (line 94)
- function: `build_index` (line 206)
- function: `_write_struct` (line 307)
- function: `_read_corpus_metadata` (line 314)
- function: `_parse_corpus_line` (line 346)
- function: `_run_pyserini_index` (line 423)
- function: `_detect_pyserini_version` (line 428)
- function: `_directory_size` (line 444)

## Tags

overlay-needed, public-api
