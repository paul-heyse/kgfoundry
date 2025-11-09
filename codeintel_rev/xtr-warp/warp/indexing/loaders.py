"""Index loading utilities for WARP indices.

This module provides functions for loading index parts, document lengths,
and residual deltas from WARP index directories.
"""

from __future__ import annotations

import pathlib
import re

import ujson


def get_parts(directory: str | pathlib.Path) -> tuple[list[int], list[str], list[str]]:
    """Get sorted index part files from a directory.

    Scans directory for .pt files and returns sorted part indices along with
    paths to part files and sample files. Validates that parts are consecutive
    integers starting from 0.

    Parameters
    ----------
    directory : str
        Directory containing index part files.

    Returns
    -------
    tuple[list[int], list[str], list[str]]
        Tuple of (part_indices, part_paths, sample_paths).

    Raises
    ------
    ValueError
        If parts are not consecutive integers starting from 0.
    """
    extension = ".pt"

    parts = sorted(
        [
            int(filename.name[: -1 * len(extension)])
            for filename in pathlib.Path(directory).iterdir()
            if filename.name.endswith(extension)
        ]
    )

    if list(range(len(parts))) != parts:
        msg = f"parts must be consecutive integers starting from 0, got {parts}"
        raise ValueError(msg)

    # Integer-sortedness matters.
    directory_obj = pathlib.Path(directory)
    parts_paths = [str(directory_obj / f"{filename}{extension}") for filename in parts]
    samples_paths = [str(directory_obj / f"{filename}.sample") for filename in parts]

    return parts, parts_paths, samples_paths


def load_doclens(
    directory: str | pathlib.Path, *, flatten: bool = True
) -> list[int] | list[list[int]]:
    """Load document lengths from index directory.

    Loads doclens from JSON files matching pattern doclens.{part}.json.
    Optionally flattens nested lists into a single list.

    Parameters
    ----------
    directory : str
        Directory containing doclens JSON files.
    flatten : bool
        Whether to flatten nested lists (default: True).

    Returns
    -------
    list[int]
        List of document lengths (flattened if flatten=True).

    Raises
    ------
    ValueError
        If no doclens files are found or loaded.
    """
    doclens_filenames = {}

    directory_obj = pathlib.Path(directory)
    for filename_path in directory_obj.iterdir():
        match = re.match(r"doclens.(\d+).json", filename_path.name)

        if match is not None:
            doclens_filenames[int(match.group(1))] = filename_path

    doclens_filenames = [doclens_filenames[i] for i in sorted(doclens_filenames.keys())]

    all_doclens = [
        ujson.load(filename_path.open(encoding="utf-8")) for filename_path in doclens_filenames
    ]

    if flatten:
        all_doclens = [x for sub_doclens in all_doclens for x in sub_doclens]

    if len(all_doclens) == 0:
        msg = "Could not load doclens"
        raise ValueError(msg)

    return all_doclens


def get_deltas(directory: str | pathlib.Path) -> tuple[list[int], list[str]]:
    """Get sorted residual delta files from a directory.

    Scans directory for .residuals.pt files and returns sorted part indices
    along with paths to residual files. Validates that parts are consecutive
    integers starting from 0.

    Parameters
    ----------
    directory : str
        Directory containing residual delta files.

    Returns
    -------
    tuple[list[int], list[str]]
        Tuple of (part_indices, residual_paths).

    Raises
    ------
    ValueError
        If parts are not consecutive integers starting from 0.
    """
    extension = ".residuals.pt"

    parts = sorted(
        [
            int(filename.name[: -1 * len(extension)])
            for filename in pathlib.Path(directory).iterdir()
            if filename.name.endswith(extension)
        ]
    )

    if list(range(len(parts))) != parts:
        msg = f"parts must be consecutive integers starting from 0, got {parts}"
        raise ValueError(msg)

    # Integer-sortedness matters.
    directory_obj = pathlib.Path(directory)
    parts_paths = [str(directory_obj / f"{filename}{extension}") for filename in parts]

    return parts, parts_paths
