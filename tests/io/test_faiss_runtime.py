"""Tests for FAISS runtime parameter application helpers."""

from __future__ import annotations

from collections.abc import Iterator
from types import ModuleType

import numpy as np
import pytest
from codeintel_rev.io import faiss_runtime

from kgfoundry_common.typing import override_gate_import
from tests._helpers import assertions

_PRIMARY_NPROBE = 64
_PRIMARY_EF_SEARCH = 128
_PRIMARY_QUANTIZER_EF = 256

_SECONDARY_NPROBE = 32
_SECONDARY_EF_SEARCH = 96
_SECONDARY_QUANTIZER_EF = 11


class _BaseStubIndex:
    """Minimal stub satisfying :class:`FaissIndex` for unit tests."""

    def __init__(self) -> None:
        self.ntotal = 0
        self.d = 0
        self.nprobe = 1
        self.is_trained = True

    def add(self, vectors: object) -> None:  # pragma: no cover - interface stub
        """Add vectors to index stub (no-op).

        Parameters
        ----------
        vectors : object
            Vectors to add (unused).
        """
        del vectors
        self.ntotal += 0

    def add_with_ids(self, vectors: object, ids: object) -> None:  # pragma: no cover
        """Add vectors with IDs to index stub (no-op).

        Parameters
        ----------
        vectors : object
            Vectors to add (unused).
        ids : object
            Vector IDs (unused).
        """
        del vectors, ids
        self.ntotal += 0

    def train(self, vectors: object) -> None:  # pragma: no cover
        """Train index stub (no-op).

        Parameters
        ----------
        vectors : object
            Training vectors (unused).
        """
        del vectors
        self.is_trained = True

    def search(self, vectors: object, k: int) -> tuple[np.ndarray, np.ndarray]:  # pragma: no cover
        """Search index stub (no-op).

        Parameters
        ----------
        vectors : object
            Query vectors (unused).
        k : int
            Number of results (unused).

        Returns
        -------
        tuple[np.ndarray, np.ndarray]
            Empty distance and ID arrays.
        """
        del vectors, k
        self.ntotal += 0
        return (
            np.empty((0, 0), dtype=np.float32),
            np.empty((0, 0), dtype=np.int64),
        )

    def make_direct_map(self) -> None:  # pragma: no cover
        """Create direct map stub (no-op)."""
        self.ntotal += 0

    def reconstruct(self, idx: int) -> np.ndarray:  # pragma: no cover
        """Reconstruct vector stub (no-op).

        Parameters
        ----------
        idx : int
            Vector index (unused).

        Returns
        -------
        np.ndarray
            Empty vector array.
        """
        del idx
        self.ntotal += 0
        return np.empty((0, 0), dtype=np.float32)


class _QuantizerStub(_BaseStubIndex):
    """Stub quantizer index for testing FAISS runtime."""

    def __init__(self) -> None:
        """Initialize stub quantizer with efSearch parameter."""
        super().__init__()
        self.efSearch = 5


class _HnswIndexStub(_BaseStubIndex):
    """Stub HNSW index for testing FAISS runtime."""

    def __init__(self) -> None:
        """Initialize stub HNSW index with quantizer."""
        super().__init__()
        self.efSearch = 16
        self.quantizer = _QuantizerStub()


class _FlatIndexStub(_BaseStubIndex):
    """Flat indexes lack HNSW and quantizer-specific attributes."""


@pytest.fixture(autouse=True)
def _skip_parameter_space() -> Iterator[None]:
    """Avoid touching real FAISS by overriding gate/parameter helpers.

    Yields
    ------
    None
        Fixture yields control to test execution with mocked FAISS module
        and parameter application overrides active.
    """
    fake_faiss = ModuleType("faiss")
    with (
        override_gate_import({"faiss": fake_faiss}),
        faiss_runtime.override_parameter_application(lambda *_args: False),
    ):
        yield


def test_apply_runtime_parameters_updates_all_supported_attributes() -> None:
    """Runtime parameters fall back to attribute assignment when needed."""
    index = _HnswIndexStub()
    faiss_runtime.apply_runtime_parameters(
        index,
        nprobe=_PRIMARY_NPROBE,
        ef_search=_PRIMARY_EF_SEARCH,
        quantizer_ef_search=_PRIMARY_QUANTIZER_EF,
    )
    assertions.expect_equal(index.nprobe, _PRIMARY_NPROBE)
    assertions.expect_equal(index.efSearch, _PRIMARY_EF_SEARCH)
    assertions.expect_equal(index.quantizer.efSearch, _PRIMARY_QUANTIZER_EF)


def test_apply_runtime_parameters_handles_missing_optional_attributes() -> None:
    """Indexes lacking optional knobs still succeed when applying overrides."""
    index = _FlatIndexStub()
    faiss_runtime.apply_runtime_parameters(
        index,
        nprobe=_SECONDARY_NPROBE,
        ef_search=_SECONDARY_EF_SEARCH,
        quantizer_ef_search=_SECONDARY_QUANTIZER_EF,
    )
    assertions.expect_equal(index.nprobe, _SECONDARY_NPROBE)
    assertions.expect_false(hasattr(index, "efSearch"))
    assertions.expect_false(hasattr(index, "quantizer"))
