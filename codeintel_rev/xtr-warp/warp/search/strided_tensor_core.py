"""Core strided tensor implementation for variable-length sequences.

This module provides StridedTensorCore for efficient storage and access
of variable-length sequences using strided views.
"""

from __future__ import annotations

from typing import Never

import numpy as np
import torch
from warp.utils.utils import flatten

# Minimum length threshold for stride selection
MIN_LENGTH_FOR_STRIDE_SELECTION = 5_000

"""
import line_profiler
import atexit
profile = line_profiler.LineProfiler()
atexit.register(profile.print_stats)
"""


class StridedTensorCore:
    """Core strided tensor for variable-length sequences.

    Stores sequences of varying lengths in a packed tensor with strided
    views for efficient access. Supports GPU acceleration.

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

    # # @profile
    def __init__(
        self,
        packed_tensor: torch.Tensor,
        lengths: torch.Tensor | list[int],
        dim: int | None = None,
        *,
        use_gpu: bool = True,
    ) -> None:
        self.dim = dim
        self.tensor = packed_tensor
        self.inner_dims = self.tensor.size()[1:]
        self.use_gpu = use_gpu

        self.lengths = lengths.long() if torch.is_tensor(lengths) else torch.LongTensor(lengths)

        self.strides = [
            *_select_strides(self.lengths, [0.5, 0.75, 0.9, 0.95]),
            self.lengths.max().item(),
        ]
        self.max_stride = self.strides[-1]

        zero = torch.zeros(1, dtype=torch.long, device=self.lengths.device)
        self.offsets = torch.cat((zero, torch.cumsum(self.lengths, dim=0)))

        if self.offsets[-2] + self.max_stride > self.tensor.size(0):
            padding = torch.zeros(
                self.max_stride,
                *self.inner_dims,
                dtype=self.tensor.dtype,
                device=self.tensor.device,
            )
            self.tensor = torch.cat((self.tensor, padding))

        self.views = {
            stride: _create_view(self.tensor, stride, self.inner_dims) for stride in self.strides
        }

    @classmethod
    def from_packed_tensor(
        cls, tensor: torch.Tensor, lengths: torch.Tensor | list[int]
    ) -> StridedTensorCore:
        """Create from packed tensor and lengths.

        Parameters
        ----------
        tensor : torch.Tensor
            Packed tensor.
        lengths : torch.Tensor | list[int]
            Sequence lengths.

        Returns
        -------
        StridedTensorCore
            New instance.
        """
        return cls(tensor, lengths)

    @classmethod
    def from_padded_tensor(cls, tensor: torch.Tensor, mask: torch.Tensor) -> None:
        """Create from padded tensor (unimplemented).

        Parameters
        ----------
        tensor : torch.Tensor
            Padded tensor.
        mask : torch.Tensor
            Attention mask.
        """

    @classmethod
    def from_nested_list(cls, lst: list[list[float]]) -> StridedTensorCore:
        """Create from nested list.

        Parameters
        ----------
        lst : list[list[float]]
            Nested list of sequences.

        Returns
        -------
        StridedTensorCore
            New instance with dim=0.
        """
        flat_lst = flatten(lst)

        tensor = torch.Tensor(flat_lst)
        lengths = [len(sublst) for sublst in lst]

        return cls(tensor, lengths, dim=0)

    @classmethod
    def from_tensors_list(cls, tensors: list[torch.Tensor]) -> Never:
        """Create from list of tensors (unimplemented).

        Parameters
        ----------
        tensors : list[torch.Tensor]
            List of tensors.

        Raises
        ------
        NotImplementedError
            Always raised.
        """
        raise NotImplementedError

    def as_packed_tensor(
        self, *, return_offsets: bool = False
    ) -> tuple[torch.Tensor, torch.Tensor] | tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Convert to packed tensor format.

        Parameters
        ----------
        return_offsets : bool
            Whether to include offsets (default: False).

        Returns
        -------
        tuple[torch.Tensor, torch.Tensor] | tuple[torch.Tensor, torch.Tensor, torch.Tensor]
            Packed tensor and lengths, optionally with offsets.
        """
        unpadded_packed_tensor = self.tensor  # [:self.offsets[-1]]

        return_vals = [unpadded_packed_tensor, self.lengths]

        if return_offsets:
            return_vals.append(self.offsets)

        return tuple(return_vals)

    # # @profile
    def as_padded_tensor(self) -> tuple[torch.Tensor, torch.Tensor]:
        """Convert to padded tensor format.

        Returns
        -------
        tuple[torch.Tensor, torch.Tensor]
            Tuple of (padded_tensor, mask).
        """
        if self.use_gpu:
            view = _create_view(self.tensor.cuda(), self.max_stride, self.inner_dims)[
                self.offsets[:-1]
            ]
            mask = _create_mask(
                self.lengths.cuda(), self.max_stride, like=view, use_gpu=self.use_gpu
            )
        else:
            view = _create_view(self.tensor, self.max_stride, self.inner_dims)
            view = view[self.offsets[:-1]]
            mask = _create_mask(self.lengths, self.max_stride, like=view, use_gpu=self.use_gpu)

        return view, mask

    def as_tensors_list(self) -> Never:
        """Convert to list of tensors (unimplemented).

        Raises
        ------
        NotImplementedError
            Always raised.
        """
        raise NotImplementedError


def _select_strides(lengths: torch.Tensor, quantiles: list[float]) -> list[int]:
    if lengths.size(0) < MIN_LENGTH_FOR_STRIDE_SELECTION:
        return _get_quantiles(lengths, quantiles)

    sample = torch.randint(0, lengths.size(0), size=(2_000,))

    return _get_quantiles(lengths[sample], quantiles)


def _get_quantiles(lengths: torch.Tensor, quantiles: list[float]) -> list[int]:
    return (
        torch.quantile(lengths.float(), torch.tensor(quantiles, device=lengths.device))
        .int()
        .tolist()
    )


def _create_view(tensor: torch.Tensor, stride: int, inner_dims: tuple[int, ...]) -> torch.Tensor:
    outdim = tensor.size(0) - stride + 1
    size = (outdim, stride, *inner_dims)

    inner_dim_prod = int(np.prod(inner_dims))
    multidim_stride = [inner_dim_prod, inner_dim_prod] + [1] * len(inner_dims)

    return torch.as_strided(tensor, size=size, stride=multidim_stride)


def _create_mask(
    lengths: torch.Tensor,
    stride: int,
    like: torch.Tensor | None = None,
    *,
    use_gpu: bool = True,
) -> torch.Tensor:
    if use_gpu:
        mask = torch.arange(stride).cuda() + 1
        mask = mask.unsqueeze(0) <= lengths.cuda().unsqueeze(-1)
    else:
        mask = torch.arange(stride) + 1
        mask = mask.unsqueeze(0) <= lengths.unsqueeze(-1)

    if like is not None:
        for _ in range(like.dim() - mask.dim()):
            mask = mask.unsqueeze(-1)

    return mask
