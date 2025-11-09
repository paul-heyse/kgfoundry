"""Configuration models for orchestration CLI operations.

This module defines typed configuration dataclasses for orchestration commands,
replacing positional arguments with keyword-only configuration objects for
improved clarity and maintainability.

Classes
-------
IndexCliConfig
    Configuration for FAISS and BM25 index building operations.
ArtifactValidationConfig
    Configuration for artifact validation operations.

Examples
--------
Create an index configuration for FAISS:

>>> from orchestration.config import IndexCliConfig
>>> config = IndexCliConfig(
...     dense_vectors="vectors.json",
...     index_path="./_indices/faiss/shard_000.idx",
...     factory="Flat",
...     metric="ip",
... )

Create a validation configuration:

>>> from orchestration.config import ArtifactValidationConfig
>>> val_config = ArtifactValidationConfig(
...     strict_mode=True,
...     fail_on_warnings=False,
... )
"""

# [nav:section public-api]

from __future__ import annotations

from dataclasses import dataclass

from kgfoundry_common.navmap_loader import load_nav_metadata

__all__ = [
    "ArtifactValidationConfig",
    "IndexCliConfig",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


@dataclass(frozen=True, slots=True)
# [nav:anchor IndexCliConfig]
class IndexCliConfig:
    """Configuration for FAISS and BM25 index building CLI operations.

    Attributes
    ----------
    dense_vectors : str
        Path to JSON file containing dense vectors in skeleton format.
    index_path : str
        Output path for the built index file.
    factory : str
        FAISS factory string (e.g., "Flat", "OPQ64,IVF8192,PQ64").
    metric : str
        Distance metric: "ip" (inner product) or "l2" (L2 distance).

    Notes
    -----
    This configuration replaces positional arguments in index_faiss CLI,
    ensuring type safety and clear parameter documentation.
    """

    dense_vectors: str
    index_path: str
    factory: str
    metric: str


@dataclass(frozen=True, slots=True)
# [nav:anchor ArtifactValidationConfig]
class ArtifactValidationConfig:
    """Configuration for artifact validation operations.

    Attributes
    ----------
    strict_mode : bool, optional
        If True, validation enforces strict schema compliance.
        Defaults to True.
    fail_on_warnings : bool, optional
        If True, warnings are treated as validation errors.
        Defaults to False.

    Notes
    -----
    This configuration supports flexible validation policies for documentation
    and index artifacts.
    """

    strict_mode: bool = True
    fail_on_warnings: bool = False
