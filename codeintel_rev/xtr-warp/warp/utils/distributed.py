"""Distributed training utilities for WARP.

This module provides functions for initializing and synchronizing
distributed training across multiple GPUs.
"""

from __future__ import annotations

import os

import torch

# NOTE: Consider torch.distributed.is_initialized() instead


def init(rank: int) -> tuple[int, bool]:
    """Initialize distributed training if needed.

    Sets up PyTorch distributed process group if WORLD_SIZE > 1 and
    CUDA is available. Idempotent: only initializes once.

    Parameters
    ----------
    rank : int
        Process rank (0-indexed).

    Returns
    -------
    tuple[int, bool]
        Tuple of (nranks, is_distributed).
    """
    nranks = "WORLD_SIZE" in os.environ and int(os.environ["WORLD_SIZE"])
    nranks = max(1, nranks)
    is_distributed = (nranks > 1) or ("WORLD_SIZE" in os.environ)

    if not hasattr(init, "already_initialized"):
        init.already_initialized = False

    if init.already_initialized:
        return nranks, is_distributed

    init.already_initialized = True

    if is_distributed and torch.cuda.is_available():
        num_gpus = torch.cuda.device_count()

        torch.cuda.set_device(rank % num_gpus)
        torch.distributed.init_process_group(backend="nccl", init_method="env://")

    return nranks, is_distributed


def barrier(rank: int) -> None:
    """Synchronize all processes at barrier.

    Blocks until all processes in distributed group reach this point.

    Parameters
    ----------
    rank : int
        Process rank (0-indexed).
    """
    nranks = "WORLD_SIZE" in os.environ and int(os.environ["WORLD_SIZE"])
    nranks = max(1, nranks)

    if rank >= 0 and nranks > 1:
        torch.distributed.barrier(device_ids=[rank % torch.cuda.device_count()])
