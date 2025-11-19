"""Helpers to build tiny Lucene indexes for smoke tests."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

import pytest

from kgfoundry_common.subprocess_utils import run_subprocess


def _write_json_collection(dir_path: Path, docs: Iterable[dict[str, str]]) -> Path:
    src = dir_path / "json"
    src.mkdir(parents=True, exist_ok=True)
    with (src / "docs.jsonl").open("w", encoding="utf-8") as handle:
        for doc in docs:
            handle.write(json.dumps(doc, ensure_ascii=False) + "\n")
    return src


def build_tiny_bm25_index(base_dir: Path) -> Path:
    """Build a minimal Lucene index for BM25 smoke tests.

    Parameters
    ----------
    base_dir : Path
        Base directory for index output.

    Returns
    -------
    Path
        Path to the created BM25 index directory.
    """
    pytest.importorskip("pyserini")
    index_dir = base_dir / "lucene-bm25"
    docs = [
        {"id": "chunk:1", "contents": "vector indexes with faiss and duckdb catalog"},
        {"id": "chunk:2", "contents": "bm25 sparse retrieval and multi field fusion"},
        {"id": "chunk:3", "contents": "splade impact search and hybrid fusion"},
    ]
    collection_dir = _write_json_collection(base_dir, docs)
    cmd: Sequence[str] = [
        sys.executable,
        "-m",
        "pyserini.index.lucene",
        "--collection",
        "JsonCollection",
        "--input",
        str(collection_dir),
        "--index",
        str(index_dir),
        "--generator",
        "DefaultLuceneDocumentGenerator",
        "--threads",
        "1",
        "--storePositions",
        "--storeDocvectors",
        "--storeRaw",
    ]
    try:
        run_subprocess(list(cmd))
    except (RuntimeError, OSError) as exc:  # pragma: no cover - best effort
        pytest.skip(f"BM25 index build failed: {exc}")
    return index_dir


def build_tiny_impact_index(base_dir: Path) -> Path:
    """Build a best-effort SPLADE impact index for smoke tests.

    Parameters
    ----------
    base_dir : Path
        Base directory for index output.

    Returns
    -------
    Path
        Path to the created impact index directory.
    """
    pytest.importorskip("pyserini")
    index_dir = base_dir / "lucene-impact"
    docs = [
        {"id": "chunk:1", "vector": "vector^1.0 indexes^0.8 faiss^0.6 duckdb^0.4"},
        {"id": "chunk:2", "vector": "bm25^1.0 sparse^0.9 retrieval^0.8 multi^0.5 field^0.5"},
        {"id": "chunk:3", "vector": "splade^1.0 impact^0.9 hybrid^0.7 fusion^0.6"},
    ]
    collection_dir = _write_json_collection(base_dir, docs)
    cmd: Sequence[str] = [
        sys.executable,
        "-m",
        "pyserini.index.lucene_impact",
        "--collection",
        "JsonVectorCollection",
        "--input",
        str(collection_dir),
        "--index",
        str(index_dir),
        "--generator",
        "DefaultLuceneImpactDocumentGenerator",
        "--threads",
        "1",
        "--impact",
        "--fields",
        "vector",
    ]
    try:
        run_subprocess(list(cmd))
    except (RuntimeError, OSError) as exc:  # pragma: no cover - best effort
        pytest.skip(f"Impact index build failed: {exc}")
    return index_dir
