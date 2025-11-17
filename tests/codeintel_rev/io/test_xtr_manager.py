"""Tests for the XTR index manager helpers."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from codeintel_rev.config.settings import XTRConfig
from codeintel_rev.io.xtr_manager import XTRIndex

from tests._helpers import assertions, constants


def _write_token_artifacts(root: Path) -> None:
    """Create token artifacts + metadata for XTR index tests."""
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
    """Index loads token artifacts and exposes metadata."""
    _write_token_artifacts(tmp_path)
    index = XTRIndex(tmp_path, XTRConfig(enable=True, dim=2, dtype="float16"))
    index.open()
    assertions.expect_true(index.ready)
    meta = index.metadata()
    assertions.expect_true(meta is not None, reason="Metadata should be available after open().")
    if meta is None:  # pragma: no cover - defensive for type checkers
        pytest.fail("Metadata should be available after open().")
    assertions.expect_sequence_equal(meta["chunk_ids"], [1, 2])
    assertions.expect_sequence_equal(meta["offsets"], [0, constants.BATCH_SIZES.minimal])


def test_xtr_index_not_ready_without_artifacts(tmp_path: Path) -> None:
    """Index stays unready when artifacts are missing."""
    index = XTRIndex(tmp_path, XTRConfig(enable=True))
    index.open()
    assertions.expect_false(index.ready)


def test_xtr_search_and_rescore(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Search returns k hits and rescoring narrows the result set."""
    _write_token_artifacts(tmp_path)
    config = XTRConfig(enable=True, dim=2, dtype="float16")
    index = XTRIndex(tmp_path, config)
    index.open()
    assertions.expect_true(index.ready)

    def _encode_query(self: XTRIndex, text: str) -> np.ndarray:
        del text, self
        return np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)

    monkeypatch.setattr(XTRIndex, "encode_query_tokens", _encode_query)
    wide_hits = index.search("query", k=2, explain=True)
    assertions.expect_equal(len(wide_hits), 2)
    assertions.expect_true(wide_hits[0][0] in {1, 2})
    narrow_hits = index.rescore("query", [1], explain=False)
    assertions.expect_equal(len(narrow_hits), 1)
