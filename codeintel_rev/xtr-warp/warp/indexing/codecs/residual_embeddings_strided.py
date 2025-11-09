"""Strided tensor wrapper for residual embeddings with passage-level access.

This module provides ResidualEmbeddingsStrided for efficient lookup of
compressed embeddings by passage ID using strided tensor indexing.
"""

from __future__ import annotations

import torch
from warp.indexing.codecs import residual_embeddings
from warp.indexing.codecs.residual import ResidualCodec
from warp.indexing.codecs.residual_embeddings import ResidualEmbeddings
from warp.search.strided_tensor import StridedTensor


class ResidualEmbeddingsStrided:
    """Strided tensor wrapper for residual embeddings with passage-level lookup.

    Wraps ResidualEmbeddings with StridedTensor indexing to enable efficient
    passage-level access and decompression. Supports GPU-accelerated lookups.

    Parameters
    ----------
    codec : ResidualCodec
        Codec for decompressing residuals.
    embeddings : ResidualEmbeddings
        Compressed embeddings container.
    doclens : list[int]
        Document lengths for strided indexing.

    Attributes
    ----------
    codec : ResidualCodec
        Codec for decompression.
    codes : torch.Tensor
        Centroid codes tensor.
    residuals : torch.Tensor
        Packed residual tensor.
    codes_strided : StridedTensor
        Strided view of codes.
    residuals_strided : StridedTensor
        Strided view of residuals.
    use_gpu : bool
        Whether GPU acceleration is enabled.
    """

    def __init__(
        self,
        codec: ResidualCodec,
        embeddings: ResidualEmbeddings,
        doclens: list[int],
    ) -> None:
        """Initialize ResidualEmbeddingsStrided with codec and embeddings.

        Parameters
        ----------
        codec : ResidualCodec
            Codec for decompressing residuals.
        embeddings : ResidualEmbeddings
            Compressed embeddings container.
        doclens : list[int]
            Document lengths for strided indexing.
        """
        self.codec = codec
        self.codes = embeddings.codes
        self.residuals = embeddings.residuals
        self.use_gpu = self.codec.use_gpu

        self.codes_strided = StridedTensor(self.codes, doclens, use_gpu=self.use_gpu)
        self.residuals_strided = StridedTensor(self.residuals, doclens, use_gpu=self.use_gpu)

    def lookup_pids(
        self,
        passage_ids: torch.Tensor | list[int],
        _out_device: str | torch.device = "cuda",
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Lookup and decompress embeddings for passage IDs.

        Retrieves codes and residuals for given passages, decompresses them,
        and returns full embeddings with code lengths.

        Parameters
        ----------
        passage_ids : torch.Tensor | list[int]
            Passage IDs to lookup.
        _out_device : str | torch.device
            Device for output tensors (default: "cuda").

        Returns
        -------
        tuple[torch.Tensor, torch.Tensor]
            Tuple of (decompressed_embeddings, codes_lengths).
        """
        codes_packed, codes_lengths = self.codes_strided.lookup(passage_ids)  # .as_packed_tensor()
        residuals_packed, _ = self.residuals_strided.lookup(passage_ids)  # .as_packed_tensor()

        embeddings_packed = self.codec.decompress(
            residual_embeddings.ResidualEmbeddings(codes_packed, residuals_packed)
        )

        return embeddings_packed, codes_lengths

    def lookup_codes(
        self, passage_ids: torch.Tensor | list[int]
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Lookup centroid codes for passage IDs.

        Retrieves codes tensor for given passages without decompression.

        Parameters
        ----------
        passage_ids : torch.Tensor | list[int]
            Passage IDs to lookup.

        Returns
        -------
        tuple[torch.Tensor, torch.Tensor]
            Tuple of (codes_packed, codes_lengths).
        """
        return self.codes_strided.lookup(passage_ids)  # .as_packed_tensor()
