"""Strided tensor for efficient variable-length sequence lookups.

This module provides StridedTensor, a wrapper around StridedTensorCore
with GPU-accelerated lookup extensions for efficient passage-level access.
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass

import torch
from torch.utils.cpp_extension import load
from warp.search.strided_tensor_core import (
    StridedTensorCore,
    create_mask,
    create_view,
)
from warp.utils.utils import print_message


class StridedTensor(StridedTensorCore):
    """Strided tensor with GPU-accelerated lookup extensions.

    Extends StridedTensorCore with CUDA extensions for faster segmented
    lookups. Supports packed and padded output formats.

    Parameters
    ----------
    packed_tensor : torch.Tensor
        Packed tensor containing all sequences.
    lengths : torch.Tensor | list[int]
        Length of each sequence.
    dim : int | None
        Inner dimension size (default: None, inferred from tensor).
    use_gpu : bool
        Whether to use GPU acceleration (default: True).
    """

    def __init__(
        self,
        packed_tensor: torch.Tensor,
        lengths: torch.Tensor | list[int],
        dim: int | None = None,
        *,
        use_gpu: bool = True,
    ) -> None:
        """Initialize StridedTensor with packed data and lengths.

        Parameters
        ----------
        packed_tensor : torch.Tensor
            Packed tensor containing all sequences.
        lengths : torch.Tensor | list[int]
            Length of each sequence.
        dim : int | None
            Inner dimension size (default: None, inferred from tensor).
        use_gpu : bool
            Whether to use GPU acceleration (default: True).
        """
        super().__init__(packed_tensor, lengths, dim=dim, use_gpu=use_gpu)

        StridedTensor.try_load_torch_extensions(use_gpu=use_gpu)


@dataclass(frozen=True)
class _StrideBatch:
    """Intermediate data produced when grouping sequences by stride."""

    order: torch.Tensor
    tensor: torch.Tensor
    lengths: torch.Tensor
    mask: torch.Tensor

    @classmethod
    def try_load_torch_extensions(cls, *, use_gpu: bool) -> None:
        """Load CUDA extensions for GPU-accelerated lookups.

        Loads segmented_lookup_cpp extension if GPU is available and extensions
        haven't been loaded yet.

        Parameters
        ----------
        use_gpu : bool
            Whether to attempt loading GPU extensions.
        """
        if hasattr(cls, "loaded_extensions") or use_gpu:
            return

        print_message(
            "Loading segmented_lookup_cpp extension "
            "(set COLBERT_LOAD_TORCH_EXTENSION_VERBOSE=True for more info)..."
        )
        segmented_lookup_cpp = load(
            name="segmented_lookup_cpp",
            sources=[
                str(pathlib.Path(__file__).parent.resolve() / "segmented_lookup.cpp"),
            ],
            extra_cflags=["-O3"],
            verbose=os.getenv("COLBERT_LOAD_TORCH_EXTENSION_VERBOSE", "False") == "True",
        )
        cls.segmented_lookup = segmented_lookup_cpp.segmented_lookup_cpp

        cls.loaded_extensions = True

    @classmethod
    def pad_packed(
        cls, packed_tensor: torch.Tensor, lengths: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Pad packed tensor to uniform length (unimplemented).

        This method is currently unimplemented and raises AssertionError.

        Parameters
        ----------
        packed_tensor : torch.Tensor
            Packed tensor to pad.
        lengths : torch.Tensor
            Sequence lengths.

        Returns
        -------
        tuple[torch.Tensor, torch.Tensor]
            Tuple of (padded_tensor, mask). Not implemented.

        Raises
        ------
        AssertionError
            Always raised, as this method is not implemented.
        """
        msg = "This seems to be incorrect but I can't see why. Is it the inner_dims in the views?"
        raise AssertionError(msg)

        packed_tensor, lengths = packed_tensor.cuda().contiguous(), lengths.cuda()

        inner_dims = packed_tensor.size()[1:]
        stride = lengths.max().item()
        offsets = torch.cumsum(lengths, dim=0) - lengths[0]

        padding = torch.zeros(
            stride, *inner_dims, device=packed_tensor.device, dtype=packed_tensor.dtype
        )
        packed_tensor = torch.cat((packed_tensor, padding))

        view = create_view(packed_tensor, stride, inner_dims)[offsets]
        mask = create_mask(lengths, stride, like=view)

        return view, mask

    def _prepare_lookup(
        self, pids: torch.Tensor | list[int]
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Prepare passage IDs for lookup.

        Normalizes pids to 1D tensor and extracts corresponding lengths
        and offsets.

        Parameters
        ----------
        pids : torch.Tensor | list[int]
            Passage IDs to lookup.

        Returns
        -------
        tuple[torch.Tensor, torch.Tensor, torch.Tensor]
            Tuple of (normalized_pids, lengths, offsets).

        Raises
        ------
        ValueError
            If pids.dim() is not 1 after conversion.
        """
        if isinstance(pids, list):
            pids = torch.tensor(pids)

        if pids.dim() != 1:
            msg = f"pids.dim() must be 1, got {pids.dim()}"
            raise ValueError(msg)

        pids = pids.long().cpu()
        lengths = self.lengths[pids]
        offsets = self.offsets[pids]

        return pids, lengths, offsets

    def lookup(
        self, pids: torch.Tensor | list[int], output: str = "packed"
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Lookup sequences for given passage IDs.

        Retrieves sequences from strided tensor, supporting packed or
        padded output formats. Uses GPU extensions if available.

        Parameters
        ----------
        pids : torch.Tensor | list[int]
            Passage IDs to lookup.
        output : str
            Output format: "packed" or "padded" (default: "packed").

        Returns
        -------
        tuple[torch.Tensor, torch.Tensor]
            Tuple of (sequences, lengths). Sequences are packed or padded
            depending on output format.

        Raises
        ------
        ValueError
            If output format is invalid or pids.dim() is not 1.
        """
        pids, lengths, offsets = self._prepare_lookup(pids)

        if self.use_gpu:
            return self._lookup_gpu(lengths, offsets, output)

        tensor = StridedTensor.segmented_lookup(self.tensor, pids, lengths, offsets)
        return tensor, lengths

    def _lookup_gpu(
        self, lengths: torch.Tensor, offsets: torch.Tensor, output: str
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Perform lookup using GPU-accelerated views."""
        stride = lengths.max().item()
        stride = next(s for s in self.strides if stride <= s)
        tensor = self.views[stride][offsets]
        if self.use_gpu:
            tensor = tensor.cuda()

        mask = create_mask(lengths, stride, use_gpu=self.use_gpu)

        if output == "padded":
            return tensor, mask

        self._ensure_packed_output(output)
        return tensor[mask], lengths

    @staticmethod
    def _ensure_packed_output(output: str) -> None:
        """Validate that the output mode is 'packed' when required."""
        if output != "packed":
            msg = f"output must be 'packed' at this point, got {output!r}"
            raise ValueError(msg)

    def lookup_staggered(
        self, pids: torch.Tensor | list[int], output: str = "packed"
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Lookup sequences with staggered padding for efficient batching.

        Retrieves sequences and pads them to maximum stride length, then
        reorders to match input order. Supports packed or padded output.

        Parameters
        ----------
        pids : torch.Tensor | list[int]
            Passage IDs to lookup.
        output : str
            Output format: "packed" or "padded" (default: "packed").

        Returns
        -------
        tuple[torch.Tensor, torch.Tensor]
            Tuple of (sequences, lengths). Sequences are packed or padded
            depending on output format.

        Raises
        ------
        ValueError
            If output format is invalid.
        """
        permute_idxs, batches = self.lookup_packed_unordered(pids)
        unordered_lengths = torch.cat([batch.lengths for batch in batches])

        output_tensor, output_mask = self._assemble_staggered_tensor(
            batches=batches,
            permute_idxs=permute_idxs,
        )

        if output == "padded":
            return output_tensor, output_mask

        self._ensure_packed_output(output)
        output_tensor = output_tensor[output_mask]
        return output_tensor, unordered_lengths[permute_idxs]

    def _assemble_staggered_tensor(
        self,
        batches: list[_StrideBatch],
        permute_idxs: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Assemble the staggered tensor layout and reorder it."""
        output_tensor = torch.empty(
            permute_idxs.size(0),
            self.max_stride,
            *self.inner_dims,
            dtype=batches[0].tensor.dtype,
            device=batches[0].tensor.device,
        )

        output_mask = torch.zeros(
            permute_idxs.size(0),
            self.max_stride,
            dtype=batches[0].mask.dtype,
            device=batches[0].mask.device,
        )

        offset = 0
        for batch in batches:
            tensor, mask = batch.tensor, batch.mask
            endpos = offset + tensor.size(0)
            output_tensor[offset:endpos, : tensor.size(1)] = tensor
            output_mask[offset:endpos, : mask.size(1)] = mask
            offset = endpos

        return output_tensor[permute_idxs], output_mask[permute_idxs]

    def lookup_packed_unordered(
        self, pids: torch.Tensor | list[int]
    ) -> tuple[torch.Tensor, list[_StrideBatch]]:
        """Lookup sequences without preserving input order.

        Retrieves sequences grouped by stride length for efficient processing.
        Returns permutation indices to restore original order.

        Parameters
        ----------
        pids : torch.Tensor | list[int]
            Passage IDs to lookup.

        Returns
        -------
        tuple[torch.Tensor, list[_StrideBatch]]
            Tuple of (permute_indices, batches grouped by stride).

        """
        pids, lengths, offsets = self._prepare_lookup(pids)

        lengths2 = lengths.clone()
        sentinel = self.strides[-1] + 1
        order = torch.arange(pids.size(0), device="cuda" if self.use_gpu else "cpu")

        batches: list[_StrideBatch] = []
        for stride in self.strides:
            is_shorter = lengths2 <= stride
            if not is_shorter.any():
                continue
            batches.append(self._build_stride_batch(stride, lengths, offsets, order, is_shorter))
            lengths2[is_shorter] = sentinel

        sentinel_tensor = torch.tensor([sentinel], device=order.device)
        if not lengths2.allclose(sentinel_tensor):
            msg = f"lengths2 must all be close to sentinel ({sentinel})"
            raise ValueError(msg)

        all_orders = torch.cat([batch.order for batch in batches])
        permute_idxs = torch.sort(all_orders).indices

        return permute_idxs, batches

    def _lookup_with_stride(
        self,
        stride: int,
        lengths: torch.Tensor,
        offsets: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        tensor = self.views[stride][offsets]
        if self.use_gpu:
            tensor = tensor.cuda()

        mask = create_mask(lengths, stride, use_gpu=self.use_gpu)

        return tensor, lengths, mask

    def _build_stride_batch(
        self,
        stride: int,
        lengths: torch.Tensor,
        offsets: torch.Tensor,
        order: torch.Tensor,
        mask: torch.Tensor,
    ) -> _StrideBatch:
        tensor_, lengths_, mask_ = self._lookup_with_stride(stride, lengths[mask], offsets[mask])
        order_subset = order[mask]
        return _StrideBatch(order_subset, tensor_, lengths_, mask_)


if __name__ == "__main__":
    """Development/testing entry point.

    Note: Pickle loading functionality has been moved to scripts/load_pickle_dev.py
    to avoid security warnings in the main codebase. Use that script for pickle operations.
    """
