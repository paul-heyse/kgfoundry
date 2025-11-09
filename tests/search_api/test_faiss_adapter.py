"""Regression tests for FAISS module adaptation helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest

from search_api.types import wrap_faiss_module

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import numpy.typing as npt

    from search_api.types import FaissIndexProtocol, IndexArray, VectorArray


class _FakeIndex:
    """Fake FAISS index for testing.

    This class provides a minimal implementation of the FAISS index protocol
    that records method calls and state changes. It's used to test FAISS
    adapter behavior without requiring actual FAISS library dependencies.

    Parameters
    ----------
    label : str
        Label identifier for this index instance, used for debugging and
        distinguishing between multiple index instances in tests.
    """

    def __init__(self, label: str) -> None:
        self.label = label
        self.last_added: VectorArray | None = None
        self.last_added_with_ids: tuple[VectorArray, IndexArray] | None = None
        self.last_trained: VectorArray | None = None

    def add(self, vectors: VectorArray) -> None:
        """Add vectors to index.

        Parameters
        ----------
        vectors : VectorArray
            Vectors to add.
        """
        self.last_added = vectors

    def search(
        self, vectors: VectorArray, k: int
    ) -> tuple[
        npt.NDArray[np.float32], npt.NDArray[np.int64]
    ]:  # pragma: no cover - minimal protocol stub
        """Search for nearest neighbors.

        Parameters
        ----------
        vectors : VectorArray
            Query vectors.
        k : int
            Number of neighbors to return.

        Returns
        -------
        tuple[npt.NDArray[np.float32], npt.NDArray[np.int64]]
            Tuple of (distances, indices).
        """
        distances = np.zeros((vectors.shape[0], k), dtype=np.float32)
        indices = np.zeros((vectors.shape[0], k), dtype=np.int64)
        return distances, indices

    def train(
        self, vectors: VectorArray
    ) -> None:  # pragma: no cover - optional protocol method
        """Train index on vectors.

        Parameters
        ----------
        vectors : VectorArray
            Training vectors.
        """
        self.last_trained = vectors

    def add_with_ids(
        self, vectors: VectorArray, ids: IndexArray
    ) -> None:  # pragma: no cover - optional protocol method
        """Add vectors with explicit IDs.

        Parameters
        ----------
        vectors : VectorArray
            Vectors to add.
        ids : IndexArray
            Vector IDs.
        """
        self.last_added_with_ids = (vectors, ids)


class _LegacyFaissModule:
    """Mock legacy FAISS module with camelCase names.

    This mock module simulates the legacy FAISS API that uses camelCase method
    names (e.g., ``indexFactory``, ``IndexFlatIP``). It records all method calls
    and provides configurable return values for testing adapter compatibility
    with legacy FAISS implementations.

    Notes
    -----
    This module uses camelCase naming conventions consistent with older FAISS
    Python bindings. The mock records method invocations to enable verification
    of adapter behavior.
    """

    METRIC_INNER_PRODUCT = 0
    METRIC_L2 = 1

    def __init__(self) -> None:
        self.index_factory_calls: list[tuple[int, str, int]] = []
        self.write_calls: list[tuple[FaissIndexProtocol, str]] = []
        self.read_path: str | None = None
        self.normalize_vectors: VectorArray | None = None
        self.index_flat_ip_dimension: int | None = None
        self.index_id_map2_index: FaissIndexProtocol | None = None

        def index_flat_ip_impl(dimension: int) -> FaissIndexProtocol:
            """Create flat IP index.

            Parameters
            ----------
            dimension : int
                Vector dimension.

            Returns
            -------
            FaissIndexProtocol
                Index instance.
            """
            self.index_flat_ip_dimension = dimension
            return _FakeIndex("flat")

        def index_id_map2_impl(index: FaissIndexProtocol) -> FaissIndexProtocol:
            """Create ID map wrapper.

            Parameters
            ----------
            index : FaissIndexProtocol
                Base index.

            Returns
            -------
            FaissIndexProtocol
                Wrapped index.
            """
            self.index_id_map2_index = index
            return _FakeIndex("idmap")

        def normalize_l2_impl(vectors: VectorArray) -> None:
            """Normalize vectors to L2 unit length.

            Parameters
            ----------
            vectors : VectorArray
                Vectors to normalize.
            """
            self.normalize_vectors = vectors

        self.IndexFlatIP: Callable[[int], FaissIndexProtocol] = index_flat_ip_impl
        self.IndexIDMap2: Callable[[FaissIndexProtocol], FaissIndexProtocol] = (
            index_id_map2_impl
        )
        self.normalize_L2: Callable[[VectorArray], None] = normalize_l2_impl

    def index_factory(
        self, dimension: int, factory_string: str, metric: int
    ) -> FaissIndexProtocol:
        """Create index using factory string.

        Parameters
        ----------
        dimension : int
            Vector dimension.
        factory_string : str
            Factory description string.
        metric : int
            Distance metric constant.

        Returns
        -------
        FaissIndexProtocol
            Index instance.
        """
        self.index_factory_calls.append((dimension, factory_string, metric))
        return _FakeIndex("factory")

    def write_index(self, index: FaissIndexProtocol, path: str) -> None:
        """Write index to file.

        Parameters
        ----------
        index : FaissIndexProtocol
            Index to write.
        path : str
            Output file path.
        """
        self.write_calls.append((index, path))

    def read_index(self, path: str) -> FaissIndexProtocol:
        """Read index from file.

        Parameters
        ----------
        path : str
            Input file path.

        Returns
        -------
        FaissIndexProtocol
            Index instance.
        """
        self.read_path = path
        return _FakeIndex("read")


class _ModernFaissModule:
    """Mock modern FAISS module with PEP-8 names.

    This mock module simulates the modern FAISS API that uses PEP-8 compliant
    method names (e.g., ``index_factory``, ``index_flat_ip``). It records all
    method calls and provides configurable return values for testing adapter
    compatibility with modern FAISS implementations.

    Notes
    -----
    This module uses PEP-8 naming conventions consistent with newer FAISS
    Python bindings. The mock records method invocations to enable verification
    of adapter behavior.
    """

    METRIC_INNER_PRODUCT = 2
    METRIC_L2 = 3

    def __init__(self) -> None:
        self.records: list[tuple[str, object]] = []

    def index_flat_ip(self, dimension: int) -> FaissIndexProtocol:
        """Create flat IP index.

        Parameters
        ----------
        dimension : int
            Vector dimension.

        Returns
        -------
        FaissIndexProtocol
            Index instance.
        """
        self.records.append(("flat", dimension))
        return _FakeIndex("flat")

    def index_factory(
        self, dimension: int, factory_string: str, metric: int
    ) -> FaissIndexProtocol:
        """Create index using factory string.

        Parameters
        ----------
        dimension : int
            Vector dimension.
        factory_string : str
            Factory description string.
        metric : int
            Distance metric constant.

        Returns
        -------
        FaissIndexProtocol
            Index instance.
        """
        self.records.append(("factory", (dimension, factory_string, metric)))
        return _FakeIndex("factory")

    def index_id_map2(self, index: FaissIndexProtocol) -> FaissIndexProtocol:
        """Create ID map wrapper.

        Parameters
        ----------
        index : FaissIndexProtocol
            Base index.

        Returns
        -------
        FaissIndexProtocol
            Wrapped index.
        """
        self.records.append(("idmap", index))
        return _FakeIndex("idmap")

    def write_index(self, index: FaissIndexProtocol, path: str) -> None:
        """Write index to file.

        Parameters
        ----------
        index : FaissIndexProtocol
            Index to write.
        path : str
            Output file path.
        """
        self.records.append(("write", (index, path)))

    def read_index(self, path: str) -> FaissIndexProtocol:
        """Read index from file.

        Parameters
        ----------
        path : str
            Input file path.

        Returns
        -------
        FaissIndexProtocol
            Index instance.
        """
        self.records.append(("read", path))
        return _FakeIndex("read")

    def normalize_l2(self, vectors: VectorArray) -> None:
        """Normalize vectors to L2 unit length.

        Parameters
        ----------
        vectors : VectorArray
            Vectors to normalize.
        """
        self.records.append(("normalize", vectors.shape))


@pytest.mark.parametrize("dimension", [5, 128])
def test_wrap_faiss_module_adapts_legacy_surface(
    dimension: int, tmp_path: Path
) -> None:
    """Test that legacy FAISS module is adapted to modern interface.

    Parameters
    ----------
    dimension : int
        Vector dimension for test.
    tmp_path : Path
        Temporary directory for file I/O tests.
    """
    legacy = _LegacyFaissModule()
    adapted = wrap_faiss_module(legacy)

    # Adapter exposes the modern PEP-8 surface while dispatching to legacy functions.
    index = adapted.index_flat_ip(dimension)
    assert isinstance(index, _FakeIndex)
    assert legacy.index_flat_ip_dimension == dimension

    mapped_index = adapted.index_id_map2(index)
    assert isinstance(mapped_index, _FakeIndex)
    assert legacy.index_id_map2_index is index

    vectors = np.ones((2, dimension), dtype=np.float32)
    adapted.normalize_l2(vectors)
    assert legacy.normalize_vectors is not None
    assert legacy.normalize_vectors.shape == vectors.shape

    factory_index = adapted.index_factory(dimension, "Flat", adapted.metric_l2)
    assert isinstance(factory_index, _FakeIndex)
    assert legacy.index_factory_calls[-1] == (dimension, "Flat", adapted.metric_l2)

    index_path = tmp_path / "index.faiss"
    adapted.write_index(factory_index, str(index_path))
    assert legacy.write_calls[-1] == (factory_index, str(index_path))

    read_index = adapted.read_index(str(index_path))
    assert isinstance(read_index, _FakeIndex)
    assert legacy.read_path == str(index_path)


def test_wrap_faiss_module_returns_pep8_module_directly() -> None:
    """Test that modern PEP-8 module is returned unchanged."""
    modern = _ModernFaissModule()
    wrapped = wrap_faiss_module(modern)

    # The helper should return the module unchanged when it already satisfies the protocol.
    assert isinstance(wrapped, _ModernFaissModule)
    assert wrapped is modern

    result = wrapped.index_flat_ip(10)
    assert isinstance(result, _FakeIndex)
    assert modern.records[0] == ("flat", 10)
