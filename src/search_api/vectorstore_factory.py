"""Dependency-injected factory for FAISS vectorstore adapters with observability.

This module provides configuration models and a factory abstraction for building
and managing FAISS indexes with structured logging, Prometheus metrics, and
RFC 9457 Problem Details error handling.

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

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from kgfoundry_common.errors import IndexBuildError
from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.prometheus import build_counter, build_histogram
from search_api.faiss_adapter import FaissAdapter

if TYPE_CHECKING:
    from kgfoundry_common.prometheus import CounterLike, HistogramLike


__all__ = [
    "FaissAdapterSettings",
    "FaissVectorstoreFactory",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


logger = logging.getLogger(__name__)

DEFAULT_INDEX_TIMEOUT_SECONDS: Final[int] = 3600
"""Default timeout for index build operations (1 hour)."""

DEFAULT_NPROBE: Final[int] = 64
"""Default nprobe parameter for IVF indexes."""

VALID_METRICS: Final[set[str]] = {"ip", "l2"}
"""Valid metric types for FAISS indexes."""

_METRIC_STAGE_LABEL = "ingestion"

_BUILD_COUNTER: CounterLike = build_counter(
    "kgfoundry_vector_ingestion_total",
    "Total FAISS vector ingestion operations",
    ("stage", "operation", "status"),
)

_BUILD_DURATION: HistogramLike = build_histogram(
    "kgfoundry_vector_ingestion_duration_seconds",
    "FAISS vector ingestion duration in seconds",
    ("stage", "operation"),
)


def _ingestion_extra(
    *, correlation_id: str | None = None, **extra_fields: object
) -> dict[str, object]:
    base = dict(extra_fields)
    if correlation_id:
        base["correlation_id"] = correlation_id
    base.setdefault("stage", _METRIC_STAGE_LABEL)
    return base


def _observe_metrics(operation: str, status: str, duration_seconds: float) -> None:
    labels = {"stage": _METRIC_STAGE_LABEL, "operation": operation, "status": status}
    _BUILD_COUNTER.labels(**labels).inc()
    _BUILD_DURATION.labels(stage=_METRIC_STAGE_LABEL, operation=operation).observe(
        duration_seconds
    )


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
    use_gpu : bool
        Enable GPU acceleration flag.
    use_cuvs : bool
        Enable cuVS acceleration flag.
    gpu_devices : tuple[int, ...]
        GPU device identifiers.
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
    use_gpu: bool = True
    """Enable GPU acceleration flag.

    Alias: none; name ``use_gpu``.
    """
    use_cuvs: bool = True
    """Enable cuVS acceleration flag.

    Alias: none; name ``use_cuvs``.
    """
    gpu_devices: tuple[int, ...] = field(default_factory=lambda: (0,))
    """GPU device identifiers.

    Alias: none; name ``gpu_devices``.
    """
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
    """Factory for building FAISS adapters with observability and error handling.

    This factory manages the lifecycle of FAISS adapter instances, emitting
    structured logs, Prometheus metrics, and Problem Details on error.

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
        logger.debug(
            "Building FAISS adapter",
            extra={
                "operation": "build_adapter",
                "factory": self.settings.factory,
                "metric": self.settings.metric,
                "gpu_enabled": self.settings.use_gpu,
            },
        )

        try:
            return FaissAdapter(
                db_path=self.settings.db_path,
                factory=self.settings.factory,
                metric=self.settings.metric,
                nprobe=self.settings.nprobe,
                use_gpu=self.settings.use_gpu,
                use_cuvs=self.settings.use_cuvs,
                gpu_devices=list(self.settings.gpu_devices),
            )
        except Exception as exc:
            msg = f"Failed to construct FAISS adapter: {exc}"
            raise IndexBuildError(msg) from exc

    def build_index(self, *, correlation_id: str | None = None) -> FaissAdapter:
        """Build a FAISS index with timeout enforcement.

        Returns
        -------
        FaissAdapter
            Configured FaissAdapter with built index.

        Raises
        ------
        IndexBuildError
            If build exceeds timeout or fails.

        Parameters
        ----------
        correlation_id : str | None, optional
            Correlation identifier propagated to logs and metrics. Defaults to ``None``.
        """
        adapter = self.build_adapter()
        start_time = time.monotonic()
        operation = "build"

        logger.info(
            "Starting FAISS index build",
            extra={
                "operation": "index_build",
                "index_path": self.settings.index_path,
                "timeout_seconds": self.settings.timeout_seconds,
                "stage": _METRIC_STAGE_LABEL,
                "correlation_id": correlation_id,
            },
        )

        try:
            adapter.build()
        except Exception as exc:
            elapsed = time.monotonic() - start_time
            logger.exception(
                "FAISS index build failed",
                extra={
                    "operation": "index_build",
                    "status": "error",
                    "duration_seconds": elapsed,
                    "error_type": type(exc).__name__,
                    "stage": _METRIC_STAGE_LABEL,
                    "correlation_id": correlation_id,
                },
            )
            _observe_metrics(operation, "error", elapsed)
            msg = f"Failed to build FAISS index: {exc}"
            raise IndexBuildError(msg, cause=exc) from exc

        elapsed = time.monotonic() - start_time

        if elapsed > self.settings.timeout_seconds:
            msg = f"Index build exceeded timeout: {elapsed:.1f}s > {self.settings.timeout_seconds}s"
            raise IndexBuildError(msg)

        vector_count = len(adapter.idmap) if adapter.idmap else 0
        matrix = adapter.cpu_matrix
        vector_dimension = matrix.shape[1] if matrix is not None else None
        logger.info(
            "FAISS index build completed",
            extra={
                "operation": "index_build",
                "status": "success",
                "duration_seconds": elapsed,
                "vector_count": vector_count,
                "vector_dimension": vector_dimension,
                "stage": _METRIC_STAGE_LABEL,
                "correlation_id": correlation_id,
            },
        )
        _observe_metrics(operation, "success", elapsed)

        return adapter

    def load_or_build(
        self, cpu_index_path: str | None = None, *, correlation_id: str | None = None
    ) -> FaissAdapter:
        """Load an existing index or build from scratch.

        Parameters
        ----------
        cpu_index_path : str | None, optional
            Path to existing CPU-format index. If provided and exists, will
            be loaded instead of rebuilding.
        correlation_id : str | None, optional
            Correlation identifier propagated to logs and metrics. Defaults to ``None``.

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

        operation = "load_or_build"
        start_time = time.monotonic()
        logger.info(
            "Loading or building FAISS index",
            extra={
                "operation": "load_or_build",
                "cpu_index_path": cpu_index_path,
                "stage": _METRIC_STAGE_LABEL,
                "correlation_id": correlation_id,
            },
        )

        try:
            adapter.load_or_build(cpu_index_path=cpu_index_path)
        except Exception as exc:
            logger.exception(
                "Index load or build failed",
                extra={
                    "operation": "load_or_build",
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "stage": _METRIC_STAGE_LABEL,
                    "correlation_id": correlation_id,
                },
            )
            msg = f"Failed to load or build FAISS index: {exc}"
            raise IndexBuildError(msg) from exc

        elapsed = time.monotonic() - start_time
        logger.info(
            "Index load or build completed",
            extra={
                "operation": "load_or_build",
                "status": "success",
                "duration_seconds": elapsed,
                "stage": _METRIC_STAGE_LABEL,
                "correlation_id": correlation_id,
            },
        )
        _observe_metrics(operation, "success", elapsed)
        return adapter

    @staticmethod
    def save_index(
        adapter: FaissAdapter,
        index_uri: str,
        idmap_uri: str | None = None,
        *,
        correlation_id: str | None = None,
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
        correlation_id : str | None, optional
            Correlation identifier propagated to logs and metrics. Defaults to ``None``.

        Raises
        ------
        IndexBuildError
            Raised when persisting the FAISS index fails. The underlying
            exception is chained for diagnostics.

        Notes
        -----
        Exceptions raised by :meth:`FaissAdapter.save` (for example I/O errors
        or FAISS errors) propagate after logging and metrics collection complete.
        """
        logger.info(
            "Saving FAISS index",
            extra={
                "operation": "save_index",
                "index_uri": index_uri,
                "idmap_uri": idmap_uri,
                "stage": _METRIC_STAGE_LABEL,
                "correlation_id": correlation_id,
            },
        )

        start_time = time.monotonic()
        operation = "save"
        try:
            adapter.save(index_uri, idmap_uri)
        except Exception as error:
            logger.exception(
                "Index save failed",
                extra={
                    "operation": "save_index",
                    "status": "error",
                    "error_type": type(error).__name__,
                    "stage": _METRIC_STAGE_LABEL,
                    "correlation_id": correlation_id,
                },
            )
            elapsed = time.monotonic() - start_time
            _observe_metrics(operation, "error", elapsed)
            message = "Failed to persist FAISS index artifacts"
            raise IndexBuildError(message) from error

        elapsed = time.monotonic() - start_time
        logger.info(
            "Index saved successfully",
            extra={
                "operation": "save_index",
                "status": "success",
                "duration_seconds": elapsed,
                "stage": _METRIC_STAGE_LABEL,
                "correlation_id": correlation_id,
            },
        )
        _observe_metrics(operation, "success", elapsed)
