"""Index file management utilities for saving and loading index parts.

This module provides IndexManager for saving tensors and bitarrays, plus
utility functions for loading compressed and uncompressed index parts.
"""

from __future__ import annotations

import pathlib

import numpy as np
import torch
from bitarray import bitarray


class IndexManager:
    """Manages saving of index tensors and bitarrays to disk.

    Provides methods for persisting PyTorch tensors and bitarrays used
    in compressed index storage.

    Parameters
    ----------
    dim : int
        Embedding dimension for index parts.

    Attributes
    ----------
    dim : int
        Embedding dimension.
    """

    def __init__(self, dim: int) -> None:
        """Initialize IndexManager with embedding dimension.

        Parameters
        ----------
        dim : int
            Embedding dimension for index parts.
        """
        self.dim = dim

    @staticmethod
    def save(tensor: torch.Tensor, path_prefix: str) -> None:
        """Save a PyTorch tensor to disk.

        Parameters
        ----------
        tensor : torch.Tensor
            Tensor to save.
        path_prefix : str
            File path prefix (extension will be added).
        """
        torch.save(tensor, path_prefix)

    @staticmethod
    def save_bitarray(bitarray: bitarray, path_prefix: str) -> None:
        """Save a bitarray to disk.

        Parameters
        ----------
        bitarray : bitarray.bitarray
            Bitarray to save.
        path_prefix : str
            File path to write to.
        """
        with pathlib.Path(path_prefix).open("wb") as f:
            bitarray.tofile(f)


def load_index_part(filename: str, *, _verbose: bool = True) -> torch.Tensor:
    """Load an uncompressed index part from disk.

    Loads a PyTorch tensor from file, handling backward compatibility
    with list-based storage format.

    Parameters
    ----------
    filename : str
        Path to index part file (.pt format).
    verbose : bool
        Whether to print loading messages (default: True).

    Returns
    -------
    torch.Tensor
        Loaded index part tensor.
    """
    part = torch.load(filename)

    if isinstance(part, list):  # for backward compatibility
        part = torch.cat(part)

    return part


def load_compressed_index_part(filename: str, dim: int, bits: int) -> torch.Tensor:
    """Load a compressed index part from bitarray file.

    Loads compressed embeddings from a bitarray file and reshapes them
    into the appropriate tensor format.

    Parameters
    ----------
    filename : str
        Path to compressed index part file.
    dim : int
        Embedding dimension.
    bits : int
        Number of quantization bits per dimension.

    Returns
    -------
    torch.Tensor
        Loaded and reshaped compressed index part tensor.
    """
    a = bitarray()

    with pathlib.Path(filename).open("rb") as f:
        a.fromfile(f)

    n = len(a) // dim // bits
    part = torch.tensor(
        np.frombuffer(a.tobytes(), dtype=np.uint8)
    )  # NOTE: isn't from_numpy(.) faster?
    return part.reshape((n, int(np.ceil(dim * bits / 8))))
