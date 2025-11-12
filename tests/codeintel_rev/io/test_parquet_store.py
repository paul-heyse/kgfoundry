"""Tests for parquet_store schema and persistence helpers."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import xxhash
from codeintel_rev.indexing.cast_chunker import Chunk
from codeintel_rev.io.parquet_store import (
    ParquetWriteOptions,
    extract_embeddings,
    get_chunks_schema,
    write_chunks_parquet,
)


def _make_chunks() -> list[Chunk]:
    return [
        Chunk(
            uri="src/app.py",
            start_byte=0,
            end_byte=12,
            start_line=0,
            end_line=0,
            text="print('hi')",
            symbols=("scip-python python demo 0.1.0 `app`/greet().",),
            language="python",
        ),
        Chunk(
            uri="src/app.py",
            start_byte=13,
            end_byte=26,
            start_line=1,
            end_line=2,
            text="def add(a, b):\n    return a + b\n",
            symbols=("scip-python python demo 0.1.0 `app`/add().",),
            language="python",
        ),
    ]


def test_schema_uses_fixed_size_embedding_and_uint64_hash() -> None:
    """Schema exposes FixedSizeList embeddings and uint64 hashes."""
    schema = get_chunks_schema(3)

    hash_field = schema.field("content_hash")
    assert hash_field.type == pa.uint64()

    embedding_field = schema.field("embedding")
    assert isinstance(embedding_field.type, pa.FixedSizeListType)
    assert embedding_field.type.list_size == 3
    assert embedding_field.type.value_field.type == pa.float32()


def test_write_chunks_parquet_roundtrip(tmp_path: Path) -> None:
    """Writer persists symbols and embeddings with stable hashes."""
    chunks = _make_chunks()
    vec_dim = 4
    embeddings = np.arange(len(chunks) * vec_dim, dtype=np.float32).reshape(len(chunks), vec_dim)
    out_path = tmp_path / "chunks.parquet"

    write_chunks_parquet(
        out_path,
        chunks,
        embeddings,
        options=ParquetWriteOptions(vec_dim=vec_dim),
    )

    assert out_path.exists()
    table = pq.read_table(out_path)
    assert table.num_rows == len(chunks)

    hashes = table.column("content_hash").to_pylist()
    expected_hashes = [
        xxhash.xxh64_intdigest(chunk.text.encode("utf-8", errors="ignore")) for chunk in chunks
    ]
    assert hashes == expected_hashes

    symbols_column = table.column("symbols").to_pylist()
    assert symbols_column == [list(chunk.symbols) for chunk in chunks]

    emb = extract_embeddings(table)
    assert emb.shape == (len(chunks), vec_dim)
    np.testing.assert_array_equal(emb, embeddings)


def test_write_chunks_parquet_rejects_dimension_mismatch(tmp_path: Path) -> None:
    """Writer raises ValueError when embeddings do not match vec_dim."""
    chunks = _make_chunks()
    embeddings = np.ones((len(chunks), 2), dtype=np.float32)
    out_path = tmp_path / "bad.parquet"

    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        write_chunks_parquet(
            out_path,
            chunks,
            embeddings,
            options=ParquetWriteOptions(vec_dim=3),
        )
