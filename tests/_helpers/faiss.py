"""Shared FAISS test helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from codeintel_rev.io.faiss_manager import FAISSManager

from tests.conftest import FAISS_MODULE, HAS_FAISS_SUPPORT

RNG = np.random.default_rng(42)

# Exported for type clarity in tests
faiss_module: Any | None = FAISS_MODULE
HAS_FAISS = HAS_FAISS_SUPPORT


def random_vectors(count: int, dim: int) -> np.ndarray:
    """Return clipped float32 vectors with a fixed RNG seed.

    Returns
    -------
    np.ndarray
        Array of shape (count, dim) with values in [0, 1].
    """
    vectors = RNG.normal(0.5, 0.15, (count, dim)).astype(np.float32)
    return np.clip(vectors, 0.0, 1.0)


def build_manager(index_path: Path, vec_dim: int) -> FAISSManager:
    """Construct a FAISSManager for tests.

    Parameters
    ----------
    index_path : Path
        Path where the FAISS index will be stored.
    vec_dim : int
        Vector dimension for the index.

    Returns
    -------
    FAISSManager
        Configured manager instance.
    """
    return FAISSManager(index_path=index_path, vec_dim=vec_dim)
