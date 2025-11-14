# bin/index_all.py

## Docstring

```
One-shot indexing: SCIP → chunk → embed → Parquet → FAISS.

This script orchestrates the full indexing pipeline:
1. Parse SCIP index for symbol definitions
2. Chunk files using cAST (SCIP-based)
3. Embed chunks with vLLM
4. Write to Parquet with embeddings
5. Build FAISS index with adaptive type selection

The FAISS index type is automatically selected based on corpus size:
- Small (<5K vectors): Flat index (exact search, fast training)
- Medium (5K-50K vectors): IVFFlat (balanced training/recall)
- Large (>50K vectors): IVF-PQ (memory efficient, fast search)
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import argparse
- from **(absolute)** import logging
- from **collections** import defaultdict
- from **collections.abc** import Mapping, Sequence
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING, Any, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.config.settings** import IndexConfig, Settings, load_settings
- from **codeintel_rev.embeddings** import get_embedding_provider
- from **codeintel_rev.evaluation.offline_recall** import OfflineRecallEvaluator
- from **codeintel_rev.indexing.cast_chunker** import Chunk, ChunkOptions, chunk_file
- from **codeintel_rev.indexing.scip_reader** import SCIPIndex, SymbolDef, extract_definitions, get_top_level_definitions, parse_scip_json
- from **codeintel_rev.io.duckdb_catalog** import DuckDBCatalog
- from **codeintel_rev.io.duckdb_manager** import DuckDBManager
- from **codeintel_rev.io.faiss_manager** import FAISSManager, FAISSRuntimeOptions
- from **codeintel_rev.io.parquet_store** import ParquetWriteOptions, write_chunks_parquet
- from **codeintel_rev.io.symbol_catalog** import SymbolCatalog, SymbolDefRow, SymbolOccurrenceRow
- from **codeintel_rev.io.vllm_client** import VLLMClient
- from **codeintel_rev.typing** import NDArrayF32
- from **(absolute)** import numpy

## Definitions

- variable: `np` (line 54)
- variable: `logger` (line 57)
- variable: `EMBED_PREVIEW_CHARS` (line 59)
- variable: `TRAINING_LIMIT` (line 60)
- class: `PipelinePaths` (line 64)
- function: `main` (line 74)
- function: `_resolve_paths` (line 149)
- function: `_load_scip_index` (line 179)
- function: `_group_definitions_by_file` (line 206)
- function: `_chunk_repository` (line 227)
- function: `_embed_chunks` (line 279)
- function: `_write_parquet` (line 309)
- function: `_build_faiss_index` (line 352)
- function: `_update_faiss_index_incremental` (line 413)
- function: `_runtime_options_from_index` (line 522)
- function: `_resolve_nlist` (line 573)
- function: `_run_offline_evaluation` (line 591)
- function: `_initialize_duckdb` (line 626)
- function: `_write_symbols` (line 657)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 13
- **cycle_group**: 68

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 20
- recent churn 90: 20

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: One-shot indexing: SCIP → chunk → embed → Parquet → FAISS.
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

- score: 2.71

## Side Effects

- filesystem

## Complexity

- branches: 38
- cyclomatic: 39
- loc: 728

## Doc Coverage

- `PipelinePaths` (class): summary=yes, examples=no — Resolved filesystem paths for the indexing pipeline.
- `main` (function): summary=yes, params=ok, examples=no — Run the end-to-end indexing pipeline.
- `_resolve_paths` (function): summary=yes, params=ok, examples=no — Resolve and normalize key filesystem paths.
- `_load_scip_index` (function): summary=yes, params=ok, examples=no — Load and parse the SCIP index from disk.
- `_group_definitions_by_file` (function): summary=yes, params=ok, examples=no — Group symbol definitions by their relative file path.
- `_chunk_repository` (function): summary=yes, params=ok, examples=no — Chunk all files referenced by the SCIP index.
- `_embed_chunks` (function): summary=yes, params=ok, examples=no — Generate embeddings for the supplied chunks using vLLM.
- `_write_parquet` (function): summary=yes, params=ok, examples=no — Persist chunk metadata and embeddings to Parquet.
- `_build_faiss_index` (function): summary=yes, params=ok, examples=no — Train and persist the FAISS index with adaptive type selection.
- `_update_faiss_index_incremental` (function): summary=yes, params=ok, examples=no — Update FAISS index incrementally by adding new chunks to secondary index.

## Tags

low-coverage
