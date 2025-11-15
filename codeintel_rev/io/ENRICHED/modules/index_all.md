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
- from **codeintel_rev.io.parquet_store** import ParquetWriteOptions, extract_embeddings, read_chunks_parquet, write_chunks_parquet
- from **codeintel_rev.io.symbol_catalog** import SymbolCatalog, SymbolDefRow, SymbolOccurrenceRow
- from **codeintel_rev.io.vllm_client** import VLLMClient
- from **codeintel_rev.typing** import NDArrayF32
- from **(absolute)** import numpy

## Definitions

- variable: `np` (line 59)
- variable: `logger` (line 62)
- variable: `EMBED_PREVIEW_CHARS` (line 64)
- variable: `TRAINING_LIMIT` (line 65)
- class: `PipelinePaths` (line 69)
- function: `main` (line 79)
- function: `_resolve_paths` (line 197)
- function: `_load_scip_index` (line 227)
- function: `_group_definitions_by_file` (line 254)
- function: `_chunk_repository` (line 275)
- function: `_embed_chunks` (line 327)
- function: `_write_parquet` (line 357)
- function: `_build_faiss_index` (line 400)
- function: `_load_embeddings_from_artifacts` (line 461)
- function: `_update_faiss_index_incremental` (line 486)
- function: `_runtime_options_from_index` (line 595)
- function: `_resolve_nlist` (line 646)
- function: `_run_offline_evaluation` (line 664)
- function: `_initialize_duckdb` (line 699)
- function: `_write_symbols` (line 730)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 13
- **cycle_group**: 71

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

- score: 2.79

## Side Effects

- filesystem

## Complexity

- branches: 50
- cyclomatic: 51
- loc: 801

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
- `_load_embeddings_from_artifacts` (function): summary=yes, params=mismatch, examples=no — Load stored embeddings from Parquet artifacts for FAISS-only runs.

## Tags

low-coverage
