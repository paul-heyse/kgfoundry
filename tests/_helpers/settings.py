"""Helpers for constructing Settings instances tailored for tests."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import msgspec
from codeintel_rev.config.settings import Settings, load_settings


def build_settings_for_repo(
    repo_root: Path,
    *,
    paths_overrides: Mapping[str, Any] | None = None,
    bm25_overrides: Mapping[str, Any] | None = None,
    splade_overrides: Mapping[str, Any] | None = None,
    index_overrides: Mapping[str, Any] | None = None,
) -> Settings:
    """Return Settings configured to point at ``repo_root``.

    Parameters
    ----------
    repo_root : Path
        Synthetic repository root used for the test scenario.
    paths_overrides, bm25_overrides, splade_overrides : Mapping[str, Any] | None
        Optional dictionaries that override the computed defaults for each section.

    Returns
    -------
    Settings
        New Settings instance whose paths/bm25/splade configs reference ``repo_root``.
    """
    base = load_settings()
    repo_root = repo_root.resolve()
    data_dir = repo_root / "data"
    default_paths = {
        "repo_root": str(repo_root),
        "data_dir": str(data_dir),
        "vectors_dir": str(data_dir / "vectors"),
        "faiss_index": str(data_dir / "faiss" / "code.ivfpq.faiss"),
        "faiss_idmap_path": str(data_dir / "faiss" / "faiss_idmap.parquet"),
        "lucene_dir": str(repo_root / "indexes"),
        "duckdb_path": str(data_dir / "catalog.duckdb"),
        "scip_index": str(repo_root / "index.scip"),
        "splade_dir": str(repo_root / "indexes" / "splade"),
        "coderank_vectors_dir": str(data_dir / "coderank_vectors"),
        "coderank_faiss_index": str(data_dir / "faiss" / "coderank.ivfpq.faiss"),
        "warp_index_dir": str(repo_root / "indexes" / "warp_xtr"),
        "xtr_dir": str(data_dir / "xtr"),
    }
    if paths_overrides:
        default_paths.update(paths_overrides)
    paths = msgspec.structs.replace(base.paths, **default_paths)

    default_bm25 = {
        "corpus_json_dir": str(data_dir / "bm25_json"),
        "index_dir": str(repo_root / "indexes" / "bm25"),
    }
    if bm25_overrides:
        default_bm25.update(bm25_overrides)
    bm25 = msgspec.structs.replace(base.bm25, **default_bm25)

    default_splade = {
        "model_dir": str(repo_root / "models" / "splade-v3"),
        "onnx_dir": str(repo_root / "models" / "splade-v3" / "onnx"),
        "onnx_file": "model_qint8.onnx",
        "vectors_dir": str(data_dir / "splade_vectors"),
        "index_dir": str(repo_root / "indexes" / "splade_v3_impact"),
    }
    if splade_overrides:
        default_splade.update(splade_overrides)
    splade = msgspec.structs.replace(base.splade, **default_splade)

    index_cfg = base.index
    if index_overrides:
        index_cfg = msgspec.structs.replace(index_cfg, **index_overrides)

    return msgspec.structs.replace(base, paths=paths, bm25=bm25, splade=splade, index=index_cfg)


__all__ = ["build_settings_for_repo"]
