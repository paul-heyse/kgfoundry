from __future__ import annotations

from pathlib import Path

import faiss
import numpy as np
from codeintel_rev.indexing.cast_chunker import Chunk
from codeintel_rev.io.parquet_store import (
    ParquetWriteOptions,
    read_chunks_parquet,
    write_chunks_parquet,
)


def _mk_chunks() -> list[Chunk]:
    return [
        Chunk(
            uri="pkg/math_ops.py",
            start_byte=0,
            end_byte=24,
            start_line=0,
            end_line=1,
            text="def add(a, b):\n    return a + b\n",
            symbols=("add",),
            language="python",
        ),
        Chunk(
            uri="pkg/math_ops.py",
            start_byte=25,
            end_byte=50,
            start_line=2,
            end_line=4,
            text="def mul(a, b):\n    return a * b\n",
            symbols=("mul",),
            language="python",
        ),
        Chunk(
            uri="pkg/arith_ext.py",
            start_byte=0,
            end_byte=28,
            start_line=0,
            end_line=2,
            text="def sub(a, b):\n    return a - b\n",
            symbols=("sub",),
            language="python",
        ),
    ]


def _mk_embeddings(chunks: list[Chunk]) -> np.ndarray:
    rng = np.random.RandomState(7)
    base = rng.randn(len(chunks), 8).astype("float32")
    base[0] = np.array([0.9, 0.9, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0], dtype="float32")
    base[2] = np.array([0.88, 0.92, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0], dtype="float32")
    base /= np.maximum(np.linalg.norm(base, axis=1, keepdims=True), 1e-8)
    return base


def test_golden_flat_exact_knn(tmp_path: Path) -> None:
    chunks = _mk_chunks()
    embeddings = _mk_embeddings(chunks)

    parquet_path = tmp_path / "chunks.parquet"
    write_chunks_parquet(
        parquet_path,
        chunks,
        embeddings,
        options=ParquetWriteOptions(start_id=0, vec_dim=embeddings.shape[1]),
    )

    table = read_chunks_parquet(parquet_path)
    assert table.num_rows == len(chunks)

    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)
    distances, ids = index.search(embeddings[0:1], 2)
    assert int(ids[0, 0]) == 0
    assert int(ids[0, 1]) == 2
    assert distances[0, 0] > distances[0, 1]
