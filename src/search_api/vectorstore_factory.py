"""Dependency-injected factory for FAISS vectorstore adapters.

This module provides configuration models and a factory abstraction for building
and managing FAISS indexes with consistent error handling.

Examples
--------
>>> from search_api.vectorstore_factory import FaissAdapterSettings, FaissVectorstoreFactory
>>> import tempfile
>>> with tempfile.TemporaryDirectory() as tmpdir:
...     settings = FaissAdapterSettings(
...         db_path="vectors.parquet",
...         index_path=f"{tmpdir}/index.idx",
...         factory="Flat",
...         metric="ip",
...     )
...     factory = FaissVectorstoreFactory(settings)
...     adapter = factory.build_adapter()
"""

# [nav:section public-api]

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Final

from kgfoundry_common.errors import IndexBuildError
from kgfoundry_common.navmap_loader import load_nav_metadata
from search_api.faiss_adapter import FaissAdapter

__all__ = [
    "FaissAdapterSettings",
    "FaissVectorstoreFactory",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


DEFAULT_INDEX_TIMEOUT_SECONDS: Final[int] = 3600
"""Default timeout for index build operations (1 hour)."""

DEFAULT_NPROBE: Final[int] = 64
"""Default nprobe parameter for IVF indexes."""

VALID_METRICS: Final[set[str]] = {"ip", "l2"}
"""Valid metric types for FAISS indexes."""


@dataclass(frozen=True, slots=True)
# [nav:anchor FaissAdapterSettings]
class FaissAdapterSettings:
    """Configuration for FAISS adapter instances.

    This immutable dataclass captures all parameters needed to construct
    a :class:`FaissAdapter` with consistent defaults and validation. Inline
    attribute docstrings describe alias usage for documentation alignment.

    Attributes
    ----------
    db_path : str
        DuckDB registry or Parquet vector path.
    index_path : str
        Filesystem path for the built index.
    factory : str
        FAISS factory string (e.g., ``"OPQ64,IVF8192,PQ64"``).
    metric : str
        Similarity metric (``"ip"`` or ``"l2"``).
    nprobe : int
        IVF search parameter ``nprobe``.
    ef_search : int | None
        Optional HNSW ``efSearch`` override.
    quantizer_ef_search : int | None
        Optional ``quantizer_efSearch`` override (useful when IVF uses HNSW quantizer).
    timeout_seconds : int
        Build timeout in seconds.

    Raises
    ------
    ValueError
        If metric is not ``"ip"`` or ``"l2"``.
    """

    db_path: str
    """DuckDB registry or Parquet vector path.

    Alias: none; name ``db_path``.
    """
    index_path: str
    """Filesystem path for the built index.

    Alias: none; name ``index_path``.
    """
    factory: str = "Flat"
    """FAISS factory string (e.g., ``"OPQ64,IVF8192,PQ64"``).

    Alias: none; name ``factory``.
    """
    metric: str = "ip"
    """Similarity metric (``"ip"`` or ``"l2"``).

    Alias: none; name ``metric``.
    """
    nprobe: int = DEFAULT_NPROBE
    """IVF search parameter ``nprobe``.

    Alias: none; name ``nprobe``.
    """
    ef_search: int | None = None
    """Optional HNSW ``efSearch`` override."""
    quantizer_ef_search: int | None = None
    """Optional ``quantizer_efSearch`` override for IVF-HNSW quantizers."""
    timeout_seconds: int = DEFAULT_INDEX_TIMEOUT_SECONDS
    """Build timeout in seconds.

    Alias: none; name ``timeout_seconds``.
    """

    def __post_init__(self) -> None:
        """Validate settings.

        Raises
        ------
        ValueError
            If ``metric`` is not one of ``{"ip", "l2"}``.
        """
        if self.metric not in VALID_METRICS:
            msg = f"metric must be 'ip' or 'l2', got {self.metric!r}"
            raise ValueError(msg)


@dataclass(slots=True, frozen=True)
# [nav:anchor FaissVectorstoreFactory]
class FaissVectorstoreFactory:
    """Factory for building FAISS adapters with error handling.

    This factory manages the lifecycle of FAISS adapter instances and raises
    IndexBuildError with Problem Details context on failure.

    Attributes
    ----------
    settings : FaissAdapterSettings
        Configuration for adapter instances.

    Examples
    --------
    >>> from search_api.vectorstore_factory import FaissAdapterSettings, FaissVectorstoreFactory
    >>> settings = FaissAdapterSettings(db_path="vectors.db", index_path="index.idx")
    >>> factory = FaissVectorstoreFactory(settings)
    """

    settings: FaissAdapterSettings

    def build_adapter(self) -> FaissAdapter:
        """Build and return a configured FAISS adapter.

        Returns
        -------
        FaissAdapter
            Configured FaissAdapter instance.

        Raises
        ------
        IndexBuildError
            If adapter construction fails.
        """
        try:
            return FaissAdapter(
                db_path=self.settings.db_path,
                factory=self.settings.factory,
                metric=self.settings.metric,
                nprobe=self.settings.nprobe,
                ef_search=self.settings.ef_search,
                quantizer_ef_search=self.settings.quantizer_ef_search,
            )
        except Exception as exc:
            msg = f"Failed to construct FAISS adapter: {exc}"
            raise IndexBuildError(msg) from exc

    def build_index(self) -> FaissAdapter:
        """Build a FAISS index with timeout enforcement.

        Returns
        -------
        FaissAdapter
            Configured FaissAdapter with built index.

        Raises
        ------
        IndexBuildError
            If build exceeds timeout or fails.
        """
        adapter = self.build_adapter()
        start_time = time.monotonic()

        try:
            adapter.build()
        except Exception as exc:
            msg = f"Failed to build FAISS index: {exc}"
            raise IndexBuildError(msg, cause=exc) from exc

        elapsed = time.monotonic() - start_time

        if elapsed > self.settings.timeout_seconds:
            msg = f"Index build exceeded timeout: {elapsed:.1f}s > {self.settings.timeout_seconds}s"
            raise IndexBuildError(msg)

        return adapter

    def load_or_build(
        self,
        cpu_index_path: str | None = None,
    ) -> FaissAdapter:
        """Load an existing index or build from scratch.

        Parameters
        ----------
        cpu_index_path : str | None, optional
            Path to existing CPU-format index. If provided and exists, will
            be loaded instead of rebuilding.

        Returns
        -------
        FaissAdapter
            Configured FaissAdapter with index ready for search.

        Raises
        ------
        IndexBuildError
            If loading or building fails.
        """
        adapter = self.build_adapter()

        try:
            adapter.load_or_build(cpu_index_path=cpu_index_path)
        except Exception as exc:
            msg = f"Failed to load or build FAISS index: {exc}"
            raise IndexBuildError(msg) from exc

        return adapter

    @staticmethod
    def save_index(
        adapter: FaissAdapter,
        index_uri: str,
        idmap_uri: str | None = None,
    ) -> None:
        """Save adapter index and ID mapping to disk.

        Parameters
        ----------
        adapter : FaissAdapter
            FaissAdapter instance with built index.
        index_uri : str
            Path where index will be saved.
        idmap_uri : str | None, optional
            Path where ID mapping will be saved.

        Raises
        ------
        IndexBuildError
            Raised when persisting the FAISS index fails. The underlying
            exception is chained for diagnostics.

        Notes
        -----
        Exceptions raised by :meth:`FaissAdapter.save` (for example I/O errors
        or FAISS errors) propagate to the caller.
        """
        try:
            adapter.save(index_uri, idmap_uri)
        except Exception as error:
            message = "Failed to persist FAISS index artifacts"
            raise IndexBuildError(message) from error
