"""Residual quantization codec for WARP index compression.

This module provides ResidualCodec for compressing embeddings using product
quantization with residual encoding. Handles compression, decompression,
and persistence of codec configurations.

EVENTUALLY: Tune the batch sizes selected here for a good balance of speed and generality.
"""

from __future__ import annotations

import os
import pathlib
from itertools import product

import numpy as np
import torch
from torch.utils.cpp_extension import load
from warp.indexing.codecs.residual_embeddings import ResidualEmbeddings
from warp.infra.config import ColBERTConfig
from warp.utils.utils import print_message


def _build_reversed_bit_map(nbits: int) -> torch.Tensor:
    """Build reversed bit map for residual repacking.

    Parameters
    ----------
    nbits : int
        Number of bits per residual component.

    Returns
    -------
    torch.Tensor
        Reversed bit map tensor (256,) in uint8.
    """
    reversed_bit_map = []
    mask = (1 << nbits) - 1
    for i in range(256):
        # The reversed byte
        z = 0
        for j in range(8, 0, -nbits):
            # Extract a subsequence of length n bits
            x = (i >> (j - nbits)) & mask

            # Reverse the endianness of each bit subsequence (e.g. 10 -> 01)
            y = 0
            for k in range(nbits - 1, -1, -1):
                y += ((x >> (nbits - k - 1)) & 1) * (2**k)

            # Set the corresponding bits in the output byte
            z |= y
            if j > nbits:
                z <<= nbits
        reversed_bit_map.append(z)
    return torch.tensor(reversed_bit_map).to(torch.uint8)


class ResidualCodec:
    """Compresses embeddings using product quantization with residual encoding.

    Encodes embeddings as centroid codes plus quantized residuals. Supports
    GPU-accelerated compression/decompression via custom CUDA extensions.
    Handles multi-dimensional codes and bucket-based residual quantization.

    Parameters
    ----------
    config : ColBERTConfig
        Configuration with dim, nbits, and rank attributes.
    centroids : torch.Tensor
        K-means centroids for quantization (num_partitions x dim).
    avg_residual : torch.Tensor | float | None
        Average residual vector or scalar for normalization (default: None).
    bucket_cutoffs : torch.Tensor | None
        Bucket boundaries for residual quantization (default: None).
    bucket_weights : torch.Tensor | None
        Bucket weights for decompression (default: None).

    Attributes
    ----------
    centroids : torch.Tensor
        Quantization centroids.
    dim : int
        Embedding dimension.
    nbits : int
        Number of quantization bits per dimension.
    avg_residual : torch.Tensor | float | None
        Average residual for normalization.
    bucket_cutoffs : torch.Tensor | None
        Bucket boundaries.
    bucket_weights : torch.Tensor | None
        Bucket weights.
    use_gpu : bool
        Whether GPU acceleration is enabled.
    rank : int
        Process rank for distributed execution.
    """

    Embeddings = ResidualEmbeddings

    def _setup_gpu_resources(
        self,
        bucket_cutoffs: torch.Tensor | None,
        bucket_weights: torch.Tensor | None,
        reversed_bit_map: torch.Tensor,
        decompression_lookup_table: torch.Tensor | None,
    ) -> tuple[torch.Tensor | None, torch.Tensor | None]:
        """Set up GPU resources for codec.

        Parameters
        ----------
        bucket_cutoffs : torch.Tensor | None
            Bucket cutoffs tensor.
        bucket_weights : torch.Tensor | None
            Bucket weights tensor.
        reversed_bit_map : torch.Tensor
            Reversed bit map tensor.
        decompression_lookup_table : torch.Tensor | None
            Decompression lookup table tensor.

        Returns
        -------
        tuple[torch.Tensor | None, torch.Tensor | None]
            Tuple of (bucket_cutoffs, bucket_weights) moved to GPU if needed.
        """
        if torch.is_tensor(bucket_cutoffs) and self.use_gpu:
            bucket_cutoffs = bucket_cutoffs.cuda()
            bucket_weights = bucket_weights.cuda() if bucket_weights is not None else None

        if self.use_gpu:
            reversed_bit_map_cuda = reversed_bit_map.cuda()
            if decompression_lookup_table is not None:
                decompression_lookup_table_cuda = decompression_lookup_table.cuda()
            else:
                decompression_lookup_table_cuda = None
        else:
            reversed_bit_map_cuda = reversed_bit_map
            decompression_lookup_table_cuda = decompression_lookup_table

        self.reversed_bit_map = reversed_bit_map_cuda
        self.decompression_lookup_table = decompression_lookup_table_cuda

        return bucket_cutoffs, bucket_weights

    def __init__(
        self,
        config: ColBERTConfig,
        centroids: torch.Tensor,
        avg_residual: torch.Tensor | float | None = None,
        bucket_cutoffs: torch.Tensor | None = None,
        bucket_weights: torch.Tensor | None = None,
    ) -> None:
        self.use_gpu = config.total_visible_gpus > 0

        ResidualCodec.try_load_torch_extensions(use_gpu=self.use_gpu)

        if self.use_gpu > 0:
            self.centroids = centroids.cuda()
        else:
            self.centroids = centroids.float()
        self.dim, self.nbits = config.dim, config.nbits
        self.avg_residual = avg_residual

        if torch.is_tensor(self.avg_residual) and self.use_gpu:
            self.avg_residual = self.avg_residual.cuda()

        bucket_cutoffs, bucket_weights = self._setup_gpu_resources(
            bucket_cutoffs, bucket_weights, _build_reversed_bit_map(self.nbits), None
        )

        self.bucket_cutoffs = bucket_cutoffs
        self.bucket_weights = bucket_weights
        if not self.use_gpu and self.bucket_weights is not None:
            self.bucket_weights = self.bucket_weights.to(torch.float32)

        self.arange_bits = torch.arange(
            0, self.nbits, device="cuda" if self.use_gpu else "cpu", dtype=torch.uint8
        )

        self.rank = config.rank

        # A table of all possible lookup orders into bucket_weights
        # given n bits per lookup
        keys_per_byte = 8 // self.nbits
        if self.bucket_weights is not None:
            decompression_lookup_table = torch.tensor(
                list(product(list(range(len(self.bucket_weights))), repeat=keys_per_byte))
            ).to(torch.uint8)
        else:
            decompression_lookup_table = None

        _, _ = self._setup_gpu_resources(
            bucket_cutoffs,
            bucket_weights,
            self.reversed_bit_map,
            decompression_lookup_table,
        )

    @classmethod
    def try_load_torch_extensions(cls, *, use_gpu: bool) -> None:
        """Load CUDA extensions for GPU-accelerated compression/decompression.

        Loads decompress_residuals_cpp and packbits_cpp extensions if GPU
        is available and extensions haven't been loaded yet.

        Parameters
        ----------
        use_gpu : bool
            Whether to attempt loading GPU extensions.
        """
        if hasattr(cls, "loaded_extensions") or not use_gpu:
            return

        print_message(
            "Loading decompress_residuals_cpp extension "
            "(set COLBERT_LOAD_TORCH_EXTENSION_VERBOSE=True for more info)..."
        )
        decompress_residuals_cpp = load(
            name="decompress_residuals_cpp",
            sources=[
                str(pathlib.Path(__file__).parent.resolve() / "decompress_residuals.cpp"),
                str(pathlib.Path(__file__).parent.resolve() / "decompress_residuals.cu"),
            ],
            verbose=os.getenv("COLBERT_LOAD_TORCH_EXTENSION_VERBOSE", "False") == "True",
        )
        cls.decompress_residuals = decompress_residuals_cpp.decompress_residuals_cpp

        print_message(
            "Loading packbits_cpp extension "
            "(set COLBERT_LOAD_TORCH_EXTENSION_VERBOSE=True for more info)..."
        )
        packbits_cpp = load(
            name="packbits_cpp",
            sources=[
                str(pathlib.Path(__file__).parent.resolve() / "packbits.cpp"),
                str(pathlib.Path(__file__).parent.resolve() / "packbits.cu"),
            ],
            verbose=os.getenv("COLBERT_LOAD_TORCH_EXTENSION_VERBOSE", "False") == "True",
        )
        cls.packbits = packbits_cpp.packbits_cpp

        cls.loaded_extensions = True

    @classmethod
    def load(cls, index_path: str | pathlib.Path) -> ResidualCodec:
        """Load codec configuration from index directory.

        Loads centroids, average residual, and bucket configuration from
        index_path and creates a ResidualCodec instance.

        Parameters
        ----------
        index_path : str | pathlib.Path
            Path to index directory containing codec files.

        Returns
        -------
        ResidualCodec
        Loaded codec instance.

        Raises
        ------
        FileNotFoundError
            If required codec files are not found.
        """
        config = ColBERTConfig.load_from_index(index_path)
        index_path_obj = pathlib.Path(index_path)
        centroids_path = index_path_obj / "centroids.pt"
        avgresidual_path = index_path_obj / "avg_residual.pt"
        buckets_path = index_path_obj / "buckets.pt"

        try:
            centroids = torch.load(centroids_path, map_location="cpu")
            avg_residual = torch.load(avgresidual_path, map_location="cpu")
            bucket_cutoffs, bucket_weights = torch.load(buckets_path, map_location="cpu")
        except FileNotFoundError as e:
            msg = f"Required codec file not found: {e.filename}"
            raise FileNotFoundError(msg) from e

        if avg_residual.dim() == 0:
            avg_residual = avg_residual.item()

        return cls(
            config=config,
            centroids=centroids,
            avg_residual=avg_residual,
            bucket_cutoffs=bucket_cutoffs,
            bucket_weights=bucket_weights,
        )

    def save(self, index_path: str | pathlib.Path) -> None:
        """Save codec configuration to index directory.

        Persists centroids, average residual, and bucket configuration
        to index_path for later loading.

        Parameters
        ----------
        index_path : str | pathlib.Path
            Path to index directory for saving codec files.

        Raises
        ------
        RuntimeError
            If avg_residual is None.
        TypeError
            If bucket_cutoffs or bucket_weights are not tensors.
        """
        if self.avg_residual is None:
            msg = "avg_residual must be set before saving"
            raise RuntimeError(msg)
        if not torch.is_tensor(self.bucket_cutoffs):
            msg = f"bucket_cutoffs must be a tensor, got {type(self.bucket_cutoffs).__name__}"
            raise TypeError(msg)
        if not torch.is_tensor(self.bucket_weights):
            msg = f"bucket_weights must be a tensor, got {type(self.bucket_weights).__name__}"
            raise TypeError(msg)

        index_path_obj = pathlib.Path(index_path)
        centroids_path = index_path_obj / "centroids.pt"
        avgresidual_path = index_path_obj / "avg_residual.pt"
        buckets_path = index_path_obj / "buckets.pt"

        torch.save(self.centroids, centroids_path)
        torch.save((self.bucket_cutoffs, self.bucket_weights), buckets_path)

        if torch.is_tensor(self.avg_residual):
            torch.save(self.avg_residual, avgresidual_path)
        else:
            torch.save(torch.tensor([self.avg_residual]), avgresidual_path)

    def compress(self, embs: torch.Tensor) -> ResidualEmbeddings:
        """Compress embeddings into codes and quantized residuals.

        Processes embeddings in batches to compute centroid codes and
        binarized residuals. Returns ResidualEmbeddings container.

        Parameters
        ----------
        embs : torch.Tensor
            Embeddings tensor to compress (num_embeddings x dim).

        Returns
        -------
        ResidualEmbeddings
            Container with codes and residuals tensors.
        """
        codes, residuals = [], []

        for batch_chunk in embs.split(1 << 18):
            batch = batch_chunk
            if self.use_gpu:
                batch = batch.cuda()
            codes_ = self.compress_into_codes(batch, out_device=batch.device)
            centroids_ = self.lookup_centroids(codes_, out_device=batch.device)

            residuals_ = batch - centroids_

            codes.append(codes_.cpu())
            residuals.append(self.binarize(residuals_).cpu())

        codes = torch.cat(codes)
        residuals = torch.cat(residuals)

        return ResidualCodec.Embeddings(codes, residuals)

    def binarize(self, residuals: torch.Tensor) -> torch.Tensor:
        """Binarize residuals using bucket quantization and bit packing.

        Quantizes residuals into buckets, expands to bit representation,
        and packs bits into uint8 tensors for efficient storage.

        Parameters
        ----------
        residuals : torch.Tensor
            Residual vectors to binarize (num_embeddings x dim).

        Returns
        -------
        torch.Tensor
            Packed binary residuals (num_embeddings x (dim // 8 * nbits)).

        Raises
        ------
        ValueError
            If dim is not divisible by 8 or (nbits * 8).
        """
        residuals = torch.bucketize(residuals.float(), self.bucket_cutoffs).to(dtype=torch.uint8)
        residuals = residuals.unsqueeze(-1).expand(
            *residuals.size(), self.nbits
        )  # add a new nbits-wide dim
        residuals >>= self.arange_bits  # divide by 2^bit for each bit position
        residuals &= 1  # apply mod 2 to binarize

        if self.dim % 8 != 0:
            msg = f"dim must be divisible by 8, got dim={self.dim}"
            raise ValueError(msg)
        if self.dim % (self.nbits * 8) != 0:
            msg = f"dim must be divisible by (nbits * 8), got dim={self.dim}, nbits={self.nbits}"
            raise ValueError(msg)

        if self.use_gpu:
            residuals_packed = ResidualCodec.packbits(residuals.contiguous().flatten())
        else:
            residuals_packed = np.packbits(np.asarray(residuals.contiguous().flatten()))
        residuals_packed = torch.as_tensor(residuals_packed, dtype=torch.uint8)
        return residuals_packed.reshape(residuals.size(0), self.dim // 8 * self.nbits)

    def compress_into_codes(
        self, embs: torch.Tensor, out_device: str | torch.device
    ) -> torch.Tensor:
        """Compute centroid codes for embeddings.

        Finds nearest centroids for each embedding via matrix multiplication
        and argmax. Processes in batches to manage memory.

        EVENTUALLY: Fusing the kernels or otherwise avoiding materializing
        the entire matrix before max(dim=0) seems like it would help here a lot.

        Parameters
        ----------
        embs : torch.Tensor
            Embeddings to encode (num_embeddings x dim).
        out_device : str | torch.device
            Device for output tensor.

        Returns
        -------
        torch.Tensor
            Centroid codes (num_embeddings,).
        """
        codes = []

        bsize = (1 << 29) // self.centroids.size(0)
        for batch in embs.split(bsize):
            if self.use_gpu:
                indices = (self.centroids @ batch.T.cuda()).max(dim=0).indices.to(device=out_device)
            else:
                indices = (
                    (self.centroids @ batch.T.cpu().float())
                    .max(dim=0)
                    .indices.to(device=out_device)
                )
            codes.append(indices)

        return torch.cat(codes)

    def lookup_centroids(self, codes: torch.Tensor, out_device: str | torch.device) -> torch.Tensor:
        """Lookup centroid vectors for given codes.

        Retrieves centroid embeddings corresponding to code indices.
        Handles multi-dimensional codes by flattening and reshaping.

        EVENTUALLY: The .split() below should happen on a flat view.

        Parameters
        ----------
        codes : torch.Tensor
            Centroid codes (any shape, values in [0, num_partitions)).
        out_device : str | torch.device
            Device for output tensor.

        Returns
        -------
        torch.Tensor
            Centroid vectors matching codes shape with dim appended.
        """
        centroids = []

        for batch in codes.split(1 << 20):
            if self.use_gpu:
                centroids.append(self.centroids[batch.cuda().long()].to(device=out_device))
            else:
                centroids.append(self.centroids[batch.long()].to(device=out_device))

        return torch.cat(centroids)

    # @profile
    def decompress(self, compressed_embs: ResidualEmbeddings) -> torch.Tensor:
        """Decompress compressed embeddings back to full-dimensional tensors.

        Batches processing even if the target device is CUDA to avoid large
        temporary buffers causing OOM.

        Parameters
        ----------
        compressed_embs : ResidualEmbeddings
            Compressed embeddings to decompress.

        Returns
        -------
        torch.Tensor
            Decompressed embeddings tensor.
        """
        codes, residuals = compressed_embs.codes, compressed_embs.residuals

        d = []
        for codes_chunk, residuals_chunk in zip(
            codes.split(1 << 15), residuals.split(1 << 15), strict=False
        ):
            codes_ = codes_chunk
            residuals_ = residuals_chunk
            if self.use_gpu:
                codes_ = codes_.cuda()
                residuals_ = residuals_.cuda()
                centroids_ = ResidualCodec.decompress_residuals(
                    residuals_,
                    self.bucket_weights,
                    self.reversed_bit_map,
                    self.decompression_lookup_table,
                    codes_,
                    self.centroids,
                    self.dim,
                    self.nbits,
                ).cuda()
            else:
                # NOTE: Remove dead code
                centroids_ = self.lookup_centroids(codes_, out_device="cpu")
                residuals_ = self.reversed_bit_map[residuals_.long()]
                residuals_ = self.decompression_lookup_table[residuals_.long()]
                residuals_ = residuals_.reshape(residuals_.shape[0], -1)
                residuals_ = self.bucket_weights[residuals_.long()]
                centroids_.add_(residuals_)

            if self.use_gpu:
                d_ = torch.nn.functional.normalize(centroids_, p=2, dim=-1)
            else:
                d_ = torch.nn.functional.normalize(centroids_.to(torch.float32), p=2, dim=-1)
            d.append(d_)

        return torch.cat(d)
