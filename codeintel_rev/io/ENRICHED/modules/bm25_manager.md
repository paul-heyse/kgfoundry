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

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 3
- **cycle_group**: 53

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 5
- recent churn 90: 5

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

BM25BuildOptions, BM25CorpusMetadata, BM25CorpusSummary, BM25IndexManager, BM25IndexMetadata

## Doc Health

- **summary**: BM25 indexing workflow helpers.
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

- score: 2.44

## Side Effects

- filesystem

## Complexity

- branches: 39
- cyclomatic: 40
- loc: 479

## Doc Coverage

- `BM25CorpusMetadata` (class): summary=yes, examples=no — Metadata describing a prepared BM25 corpus.
- `BM25CorpusSummary` (class): summary=yes, examples=no — Summary information returned after preparing a corpus.
- `BM25IndexMetadata` (class): summary=yes, examples=no — Metadata describing a built BM25 index.
- `BM25BuildOptions` (class): summary=yes, examples=no — Options controlling BM25 index builds.
- `BM25IndexManager` (class): summary=yes, examples=no — Manage BM25 corpus preparation and Lucene index builds.
- `_write_struct` (function): summary=yes, params=mismatch, examples=no — Write a msgspec struct to JSON with UTF-8 encoding.
- `_read_corpus_metadata` (function): summary=yes, params=ok, examples=no — Read corpus metadata from JSON file.
- `_parse_corpus_line` (function): summary=yes, params=ok, examples=no — Parse and validate a JSONL line from the corpus source.
- `_run_pyserini_index` (function): summary=yes, params=mismatch, examples=no — Execute the Pyserini index command and raise for failures.
- `_detect_pyserini_version` (function): summary=yes, params=ok, examples=no — Return the installed Pyserini version or ``'unknown'`` if unavailable.

## Tags

low-coverage, public-api
