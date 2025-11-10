from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from codeintel_rev.config.settings import XTRConfig
from codeintel_rev.io.xtr_manager import XTRIndex


def _write_token_artifacts(root: Path) -> None:
    token_path = root / "tokens.f16"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    data = np.asarray(
        [
            [1.0, 0.0],
            [0.0, 1.0],
            [0.5, 0.5],
        ],
        dtype=np.float16,
    )
    memmap = np.memmap(token_path, mode="w+", dtype=np.float16, shape=data.shape)
    memmap[:] = data
    memmap.flush()
    meta = {
        "dim": 2,
        "dtype": "float16",
        "total_tokens": 3,
        "doc_count": 2,
        "chunk_ids": [1, 2],
        "offsets": [0, 2],
        "lengths": [2, 1],
    }
    with (root / "index.meta.json").open("w", encoding="utf-8") as handle:
        json.dump(meta, handle)


def test_xtr_index_open_and_metadata(tmp_path: Path) -> None:
    _write_token_artifacts(tmp_path)
    index = XTRIndex(tmp_path, XTRConfig(enable=True, dim=2, dtype="float16"))
    index.open()
    assert index.ready
    meta = index.metadata()
    assert meta is not None
    assert meta["chunk_ids"] == [1, 2]
    assert meta["offsets"] == [0, 2]


def test_xtr_index_not_ready_without_artifacts(tmp_path: Path) -> None:
    index = XTRIndex(tmp_path, XTRConfig(enable=True))
    index.open()
    assert not index.ready


def test_xtr_search_and_rescore(tmp_path: Path) -> None:
    _write_token_artifacts(tmp_path)
    config = XTRConfig(enable=True, dim=2, dtype="float16")
    index = XTRIndex(tmp_path, config)
    index.open()
    assert index.ready
    def _encode_query(text: str) -> np.ndarray:
        del text
        return np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)

    object.__setattr__(index, "encode_query_tokens", _encode_query)
    wide_hits = index.search("query", k=2, explain=True)
    assert len(wide_hits) == 2
    assert wide_hits[0][0] in {1, 2}
    narrow_hits = index.rescore("query", [1], explain=False)
    assert len(narrow_hits) == 1
