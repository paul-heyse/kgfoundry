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
- from **(absolute)** import parquet
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.typing** import NDArrayF32
- from **collections.abc** import Sequence
- from **(absolute)** import numpy
- from **codeintel_rev.indexing.cast_chunker** import Chunk

## Definitions

- function: `get_chunks_schema` (line 29)
- class: `ParquetWriteOptions` (line 59)
- function: `write_chunks_parquet` (line 67)
- function: `read_chunks_parquet` (line 145)
- function: `extract_embeddings` (line 161)

## Tags

overlay-needed, public-api
