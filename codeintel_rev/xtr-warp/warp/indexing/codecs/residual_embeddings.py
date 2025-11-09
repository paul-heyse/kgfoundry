"""Residual embeddings storage for ColBERT indexing.

This module provides ResidualEmbeddings class for storing compressed
residual embeddings with codes for efficient retrieval.
"""

from __future__ import annotations

import pathlib
from collections.abc import Sequence

import torch
import tqdm
import ujson
from warp.indexing.codecs.residual_embeddings_strided import ResidualEmbeddingsStrided
from warp.utils.utils import print_message

# Expected tensor dimensions
EXPECTED_CODES_DIM = 1
EXPECTED_RESIDUALS_DIM = 2


class ResidualEmbeddings:
    """Container for compressed residual embeddings used in ColBERT indexing.

    This class stores already compressed residuals along with their corresponding
    codes. The residuals are expected to be pre-compressed before being passed to
    this constructor.

    Parameters
    ----------
    codes : torch.Tensor
        Tensor containing the codes for embeddings. Must be 1-dimensional and
        have the same size(0) as residuals. After initialization, this is converted
        to int32 format and stored as the ``codes`` instance attribute.
    residuals : torch.Tensor
        Tensor containing the compressed residual embeddings. Must be 2-dimensional
        with size(0) matching codes.size(0), and dtype must be torch.uint8.
        After initialization, this is stored as the ``residuals`` instance attribute.

    Attributes
    ----------
    Strided
        Class attribute referencing the strided variant class for residual embeddings.
        Type: :class:`ResidualEmbeddingsStrided`
    """

    Strided = ResidualEmbeddingsStrided

    def __init__(self, codes: torch.Tensor, residuals: torch.Tensor) -> None:
        if codes.size(0) != residuals.size(0):
            msg = (
                f"codes.size(0) ({codes.size(0)}) must equal "
                f"residuals.size(0) ({residuals.size(0)})"
            )
            raise ValueError(msg)
        if (
            codes.dim() != EXPECTED_CODES_DIM
            or residuals.dim() != EXPECTED_RESIDUALS_DIM
        ):
            msg = (
                "codes must be 1-dimensional and residuals must be "
                f"2-dimensional, got codes.size()={codes.size()}, "
                f"residuals.size()={residuals.size()}"
            )
            raise ValueError(msg)
        if residuals.dtype != torch.uint8:
            msg = f"residuals.dtype must be torch.uint8, got {residuals.dtype}"
            raise ValueError(msg)

        self.codes = codes.to(torch.int32)  # (num_embeddings,) int32
        self.residuals = residuals  # (num_embeddings, compressed_dim) uint8

    @classmethod
    def load_chunks(
        cls,
        index_path: str | pathlib.Path,
        chunk_idxs: Sequence[int],
        num_embeddings: int,
        *,
        load_index_with_mmap: bool = False,
    ) -> ResidualEmbeddings:
        """Load embeddings from multiple chunks.

        Loads codes and residuals from multiple index chunks, optionally
        using memory mapping for single-chunk indices.

        Parameters
        ----------
        index_path : str | pathlib.Path
            Path to index directory.
        chunk_idxs : Sequence[int]
            Chunk indices to load.
        num_embeddings : int
            Total number of embeddings (padded by 512).
        load_index_with_mmap : bool
            Whether to use memory mapping (default: False).

        Returns
        -------
        ResidualEmbeddings
            Loaded embeddings instance.

        Notes
        -----
        This method may raise ValueError if load_index_with_mmap=True and
        len(chunk_idxs) != 1. The exception is raised indirectly by
        _load_chunks_with_mmap or _load_chunks_without_mmap when validation fails.
        """
        num_embeddings += 512  # pad for access with strides
        dim, nbits = get_dim_and_nbits(index_path)
        if load_index_with_mmap:
            return cls._load_chunks_with_mmap(index_path, chunk_idxs)
        return cls._load_chunks_streaming(
            index_path, chunk_idxs, num_embeddings, dim, nbits
        )

    @classmethod
    def _load_chunks_with_mmap(
        cls,
        index_path: str | pathlib.Path,
        chunk_idxs: Sequence[int],
    ) -> ResidualEmbeddings:
        if len(chunk_idxs) != 1:
            msg = (
                "Index must only have 1 chunk to load with memory mapping!"
                "Use the colbert/utils/coalesce.py to prepare index for memory mapping."
            )
            raise ValueError(msg)

        print_message("#> Loading codes and residuals with memory mapping...")
        index_path_obj = pathlib.Path(index_path)
        residuals_path = index_path_obj / "0.residuals.pt"
        codes_path = index_path_obj / "0.codes.pt"

        codes_size = get_codes_size(index_path, 0)
        storage = torch.IntStorage.from_file(
            filename=codes_path, shared=True, size=codes_size + 80
        )
        codes = torch.IntTensor(storage)[80:]

        residuals_size, codes_size, packed_dim = get_residuals_size(index_path, 0)
        storage = torch.ByteStorage.from_file(
            filename=residuals_path, shared=True, size=residuals_size + 320
        )
        residuals = torch.ByteTensor(storage)
        residuals = residuals[320:]
        residuals = torch.reshape(residuals, (codes_size, packed_dim))

        return cls(codes, residuals)

    @classmethod
    def _load_chunks_streaming(
        cls,
        index_path: str | pathlib.Path,
        chunk_idxs: Sequence[int],
        num_embeddings: int,
        dim: int,
        nbits: int,
    ) -> ResidualEmbeddings:
        print_message("#> Loading codes and residuals...")
        codes = torch.empty(num_embeddings, dtype=torch.int32)
        residuals = torch.empty(num_embeddings, dim // 8 * nbits, dtype=torch.uint8)

        cls._populate_chunk_storage(index_path, chunk_idxs, codes, residuals)
        return cls(codes, residuals)

    @classmethod
    def _populate_chunk_storage(
        cls,
        index_path: str | pathlib.Path,
        chunk_idxs: Sequence[int],
        codes: torch.Tensor,
        residuals: torch.Tensor,
    ) -> None:
        codes_offset = 0
        for chunk_idx in tqdm.tqdm(chunk_idxs):
            chunk = cls.load(index_path, chunk_idx)
            codes_endpos = codes_offset + chunk.codes.size(0)
            codes[codes_offset:codes_endpos] = chunk.codes
            residuals[codes_offset:codes_endpos] = chunk.residuals
            codes_offset = codes_endpos

    @classmethod
    def load(cls, index_path: str | pathlib.Path, chunk_idx: int) -> ResidualEmbeddings:
        """Load embeddings from a single chunk.

        Parameters
        ----------
        index_path : str | pathlib.Path
            Path to index directory.
        chunk_idx : int
            Chunk index to load.

        Returns
        -------
        ResidualEmbeddings
            Loaded embeddings instance.
        """
        codes = cls.load_codes(index_path, chunk_idx)
        residuals = cls.load_residuals(index_path, chunk_idx)

        return cls(codes, residuals)

    @classmethod
    def load_codes(cls, index_path: str | pathlib.Path, chunk_idx: int) -> torch.Tensor:
        """Load codes tensor from chunk.

        Parameters
        ----------
        index_path : str | pathlib.Path
            Path to index directory.
        chunk_idx : int
            Chunk index.

        Returns
        -------
        torch.Tensor
            Codes tensor (int32).
        """
        codes_path = pathlib.Path(index_path) / f"{chunk_idx}.codes.pt"
        return torch.load(codes_path, map_location="cpu")

    @classmethod
    def load_residuals(
        cls, index_path: str | pathlib.Path, chunk_idx: int
    ) -> torch.Tensor:
        """Load residuals tensor from chunk.

        Parameters
        ----------
        index_path : str | pathlib.Path
            Path to index directory.
        chunk_idx : int
            Chunk index.

        Returns
        -------
        torch.Tensor
            Residuals tensor (uint8).
        """
        residuals_path = pathlib.Path(index_path) / f"{chunk_idx}.residuals.pt"

        return torch.load(residuals_path, map_location="cpu")

    def save(self, path_prefix: str) -> None:
        """Save embeddings to disk.

        Saves codes and residuals to separate files with given prefix.

        Parameters
        ----------
        path_prefix : str
            Path prefix for output files (e.g., "chunk.0").
        """
        codes_path = f"{path_prefix}.codes.pt"
        residuals_path = f"{path_prefix}.residuals.pt"

        torch.save(self.codes, codes_path)
        torch.save(self.residuals, residuals_path)

    def __len__(self) -> int:
        """Get number of embeddings.

        Returns
        -------
        int
            Number of embeddings (size of codes tensor).
        """
        return self.codes.size(0)


def get_dim_and_nbits(index_path: str | pathlib.Path) -> tuple[int, int]:
    """Get embedding dimension and quantization bits from metadata.

    Parameters
    ----------
    index_path : str | pathlib.Path
        Path to index directory.

    Returns
    -------
    tuple[int, int]
        Tuple of (dim, nbits).

    Raises
    ------
    ValueError
        If (dim * nbits) is not divisible by 8.
    """
    # NOTE: Ideally load this using ColBERTConfig.load_from_index!
    with (pathlib.Path(index_path) / "metadata.json").open(encoding="utf-8") as f:
        metadata = ujson.load(f)["config"]

    dim = metadata["dim"]
    nbits = metadata["nbits"]

    if (dim * nbits) % 8 != 0:
        msg = (
            f"(dim * nbits) must be divisible by 8, got dim={dim}, "
            f"nbits={nbits}, dim*nbits={dim * nbits}"
        )
        raise ValueError(msg)

    return dim, nbits


def get_codes_size(index_path: str | pathlib.Path, chunk_idx: int) -> int:
    """Get number of embeddings in chunk from metadata.

    Parameters
    ----------
    index_path : str | pathlib.Path
        Path to index directory.
    chunk_idx : int
        Chunk index.

    Returns
    -------
    int
        Number of embeddings in chunk.
    """
    # NOTE: Ideally load this using ColBERTConfig.load_from_index!
    with (pathlib.Path(index_path) / f"{chunk_idx}.metadata.json").open(
        encoding="utf-8"
    ) as f:
        metadata = ujson.load(f)

    return metadata["num_embeddings"]


def get_residuals_size(
    index_path: str | pathlib.Path, chunk_idx: int
) -> tuple[int, int, int]:
    """Get residuals size information for chunk.

    Parameters
    ----------
    index_path : str | pathlib.Path
        Path to index directory.
    chunk_idx : int
        Chunk index.

    Returns
    -------
    tuple[int, int, int]
        Tuple of (total_bytes, num_embeddings, packed_dim).
    """
    codes_size = get_codes_size(index_path, chunk_idx)
    dim, nbits = get_dim_and_nbits(index_path)

    packed_dim = dim // 8 * nbits
    return codes_size * packed_dim, codes_size, packed_dim
