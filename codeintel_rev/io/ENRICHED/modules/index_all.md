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
- from **codeintel_rev.config.settings** import IndexConfig, Settings, VLLMConfig, load_settings
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

- class: `PipelinePaths` (line 68)
- function: `main` (line 78)
- function: `_resolve_paths` (line 153)
- function: `_resolve` (line 168)
- function: `_load_scip_index` (line 183)
- function: `_group_definitions_by_file` (line 210)
- function: `_chunk_repository` (line 231)
- function: `_embed_chunks` (line 283)
- function: `_write_parquet` (line 305)
- function: `_build_faiss_index` (line 347)
- function: `_update_faiss_index_incremental` (line 408)
- function: `_runtime_options_from_index` (line 517)
- function: `_resolve_nlist` (line 568)
- function: `_run_offline_evaluation` (line 586)
- function: `_initialize_duckdb` (line 621)
- function: `_write_symbols` (line 651)
- function: `_chunk_for` (line 661)

## Tags

overlay-needed
