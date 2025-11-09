"""Index size calculation utilities for WARP and Plaid indexes.

This module provides functions to calculate the size of index files on disk,
supporting both WARP-compressed indexes and Plaid indexes. It handles
recursive directory traversal and file size aggregation.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from warp.engine.config import WARPRunConfig

load_dotenv()

DATASETS = [
    "beir.nfcorpus",
    "beir.scifact",
    "beir.scidocs",
    "beir.fiqa",
    "beir.webis-touche2020",
    "beir.quora",
    "lotte.lifestyle",
    "lotte.recreation",
    "lotte.writing",
    "lotte.technology",
    "lotte.science",
    "lotte.pooled",
]
NBITS_VALUES = [2, 4]

WARP_FILES = [
    "bucket_weights.npy",
    "centroids.npy",
    "sizes.compacted.pt",
    "codes.compacted.pt",
    "residuals.repacked.compacted.pt",
]
IGNORED_FILES = ["residuals.compacted.pt", "avg_centroids.pt", "bucket_cutoffs.npy"]
SHARED_FILES = ["ivf.pid.pt"]


def filesize(path: str | Path) -> int:
    """Calculate the total size of a file or directory in bytes.

    Recursively sums the size of all files if the path is a directory.
    Returns 0 for non-existent paths.

    Parameters
    ----------
    path : str | Path
        File or directory path to measure.

    Returns
    -------
    int
        Total size in bytes (0 if path doesn't exist).
    """
    path_obj = Path(path)
    if path_obj.is_file():
        return path_obj.stat().st_size
    return sum(filesize(path_obj / file.name) for file in path_obj.iterdir())


def warp_index_size(index_path: str | Path) -> int:
    """Calculate the total size of a WARP-compressed index.

    Sums the size of all WARP index files including bucket weights,
    centroids, compacted codes/residuals, and shared IVF files.

    Parameters
    ----------
    index_path : str | Path
        Path to the WARP index directory.

    Returns
    -------
    int
        Total index size in bytes.
    """
    total_size = 0
    index_path_obj = Path(index_path)
    for entry in WARP_FILES + SHARED_FILES:
        total_size += filesize(index_path_obj / entry)
    return total_size


def plaid_index_size(index_path: str | Path) -> int:
    """Calculate the total size of a Plaid index.

    Sums the size of all files in the index directory except for WARP-specific
    files and ignored files (like uncompacted residuals).

    Parameters
    ----------
    index_path : str | Path
        Path to the Plaid index directory.

    Returns
    -------
    int
        Total index size in bytes.
    """
    total_size = 0
    index_path_obj = Path(index_path)
    for entry in index_path_obj.iterdir():
        if entry.name not in (WARP_FILES + IGNORED_FILES):
            total_size += filesize(entry)
    return total_size


def bytes_to_gib(size: int) -> float:
    """Convert bytes to gibibytes (GiB).

    Parameters
    ----------
    size : int
        Size in bytes.

    Returns
    -------
    float
        Size in gibibytes (1024^3 bytes).
    """


def safe_index_size(config: WARPRunConfig) -> int | None:
    """Calculate index size safely, returning None on errors.

    Attempts to calculate the WARP index size from the configuration.
    Returns None if the index path doesn't exist or if any error occurs
    during size calculation.

    Parameters
    ----------
    config : WARPRunConfig
        WARP run configuration containing index path information.

    Returns
    -------
    int | None
        Index size in bytes, or None if calculation fails.
    """
    index_path = config.colbert().index_path
    try:
        return warp_index_size(index_path)
    except (OSError, ValueError):
        return None
