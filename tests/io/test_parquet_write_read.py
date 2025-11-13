"""Regression tests for chunk Parquet helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from codeintel_rev.indexing.cast_chunker import Chunk
from codeintel_rev.io.parquet_store import ParquetWriteOptions, write_chunks_parquet


def _make_chunk() -> Chunk:
    return Chunk(
        uri="src/app.py",
        start_byte=0,
        end_byte=12,
        start_line=0,
        end_line=0,
        text="print('hi')",
        symbols=("scip-python python demo 0.1.0 `app`/greet().",),
        language="python",
    )


def test_parquet_metadata_round_trip(tmp_path: Path) -> None:
    """Custom schema metadata is persisted alongside vectors."""
    chunk = _make_chunk()
    embeddings = np.ones((1, 4), dtype=np.float32)
    out_path = tmp_path / "chunks.parquet"
    meta = {
        "embedding_model": "unit-test",
        "embedding_provider": "stub",
        "embedding_dim": "4",
    }

    write_chunks_parquet(
        out_path,
        [chunk],
        embeddings,
        options=ParquetWriteOptions(vec_dim=4, table_meta=meta),
    )

    table = pq.read_table(out_path)
    schema_meta = table.schema.metadata
    assert schema_meta is not None
    for key, value in meta.items():
        assert schema_meta.get(key.encode("utf-8")) == value.encode("utf-8")
