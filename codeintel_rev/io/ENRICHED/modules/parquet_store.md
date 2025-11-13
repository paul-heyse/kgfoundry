# io/parquet_store.py

## Docstring

```
Parquet storage for chunks and vectors using Arrow.

Stores chunks and embeddings in columnar Parquet format with FixedSizeList
for efficient vector storage and querying via DuckDB.
```

## Imports

- from **__future__** import annotations
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING, cast
- from **(absolute)** import pyarrow
- from **(absolute)** import pyarrow.parquet
- from **(absolute)** import xxhash
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.typing** import NDArrayF32
- from **collections.abc** import Sequence
- from **(absolute)** import numpy
- from **codeintel_rev.indexing.cast_chunker** import Chunk

## Definitions

- variable: `np` (line 27)
- function: `get_chunks_schema` (line 30)
- variable: `EMBEDDINGS_RANK` (line 64)
- class: `ParquetWriteOptions` (line 68)
- function: `_hash_content` (line 76)
- function: `write_chunks_parquet` (line 88)
- function: `read_chunks_parquet` (line 166)
- function: `extract_embeddings` (line 182)

## Graph Metrics

- **fan_in**: 2
- **fan_out**: 3
- **cycle_group**: 56

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 16
- recent churn 90: 16

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

ParquetWriteOptions, extract_embeddings, get_chunks_schema, read_chunks_parquet, write_chunks_parquet

## Doc Health

- **summary**: Parquet storage for chunks and vectors using Arrow.
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

- score: 1.89

## Side Effects

- filesystem

## Complexity

- branches: 6
- cyclomatic: 7
- loc: 220

## Doc Coverage

- `get_chunks_schema` (function): summary=yes, params=ok, examples=no — Get Arrow schema for chunks table.
- `ParquetWriteOptions` (class): summary=yes, examples=no — Configuration for Parquet persistence.
- `_hash_content` (function): summary=yes, params=mismatch, examples=no — Return stable 64-bit hash of chunk content.
- `write_chunks_parquet` (function): summary=yes, params=ok, examples=no — Write chunks and embeddings to Parquet.
- `read_chunks_parquet` (function): summary=yes, params=ok, examples=no — Read chunks from Parquet file.
- `extract_embeddings` (function): summary=yes, params=ok, examples=no — Extract embeddings from chunks table.

## Tags

low-coverage, public-api
