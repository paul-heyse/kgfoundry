"""Index format conversion utilities for WARP.

This module provides functions for converting between different index formats,
including segmented cumsum operations and WARP-compacted index conversion.
"""

from __future__ import annotations

import json
import pathlib
from itertools import product

import numpy as np
import torch
from tqdm import tqdm
from warp.modeling.xtr import DOC_MAXLEN, QUERY_MAXLEN

# Residual compression bit widths
NBITS_4 = 4
NBITS_2 = 2


def segmented_index_cumsum(
    input_tensor: torch.Tensor, offsets: torch.Tensor
) -> tuple[torch.Tensor, torch.Tensor]:
    """Compute segmented cumulative sum with indices.

    Computes cumulative sum within segments defined by offsets, returning
    indices and updated offsets.

    Parameters
    ----------
    input_tensor : torch.Tensor
        Input tensor to sort and segment.
    offsets : torch.Tensor
        Initial offsets for each segment.

    Returns
    -------
    tuple[torch.Tensor, torch.Tensor]
        Tuple of (indices, updated_offsets).
    """
    values, indices = input_tensor.sort(stable=True)
    unique_values, inverse_indices, counts_values = torch.unique(
        values, return_inverse=True, return_counts=True
    )
    offset_arange = torch.arange(1, len(unique_values) + 1)
    offset_count_indices = offset_arange[inverse_indices]

    offset_counts = torch.zeros(counts_values.shape[0] + 1, dtype=torch.long)
    offset_counts[1:] = torch.cumsum(counts_values, dim=0)

    counts = torch.zeros_like(input_tensor, dtype=torch.long)
    counts[indices] = (
        torch.arange(0, input_tensor.shape[0]) - offset_counts[offset_count_indices - 1]
    )

    return counts + offsets[input_tensor.long()], offsets + torch.bincount(
        input_tensor, minlength=offsets.shape[0]
    )


def convert_index(index_path: str, destination_path: str | None = None) -> None:
    """Convert index to WARP-compacted format.

    Converts a standard ColBERT index to WARP-compacted format with repacked
    residuals, compacted codes, and bucket weights. Requires XTR-base-en checkpoint.

    Parameters
    ----------
    index_path : str
        Path to source index directory.
    destination_path : str | None
        Path to destination directory (default: None, overwrites source).

    Raises
    ------
    ValueError
        If checkpoint is not 'google/xtr-base-en', query_maxlen/doc_maxlen
        don't match expected values, or tensor shapes are invalid.
    AssertionError
        If nbits is not 2 or 4.
    """
    if destination_path is None:
        destination_path = index_path
    pathlib.Path(destination_path).mkdir(exist_ok=True, parents=True)
    index_path_obj = pathlib.Path(index_path)
    with (index_path_obj / "plan.json").open(encoding="utf-8") as file:
        plan = json.load(file)

    config = plan["config"]

    checkpoint = config["checkpoint"]
    if checkpoint != "google/xtr-base-en":
        msg = f"checkpoint must be 'google/xtr-base-en', got {checkpoint!r}"
        raise ValueError(msg)

    dim = config["dim"]
    nbits = config["nbits"]

    query_maxlen = config["query_maxlen"]
    doc_maxlen = config["doc_maxlen"]

    if query_maxlen != QUERY_MAXLEN:
        msg = f"query_maxlen must be {QUERY_MAXLEN}, got {query_maxlen}"
        raise ValueError(msg)
    if doc_maxlen != DOC_MAXLEN:
        msg = f"doc_maxlen must be {DOC_MAXLEN}, got {doc_maxlen}"
        raise ValueError(msg)

    num_chunks = plan["num_chunks"]
    num_partitions = plan["num_partitions"]  # i.e., num_centroids

    centroids = torch.load(index_path_obj / "centroids.pt", map_location="cpu")
    if centroids.shape != (num_partitions, dim):
        msg = f"centroids.shape must be ({num_partitions}, {dim}), got {centroids.shape}"
        raise ValueError(msg)

    # NOTE(jlscheerer): Perhaps do this per centroid instead of globally.
    bucket_cutoffs, bucket_weights = torch.load(index_path_obj / "buckets.pt", map_location="cpu")

    destination_path_obj = pathlib.Path(destination_path)
    np.save(
        destination_path_obj / "bucket_cutoffs.npy",
        bucket_cutoffs.float().numpy(force=True),
    )
    np.save(
        destination_path_obj / "bucket_weights.npy",
        bucket_weights.float().numpy(force=True),
    )

    centroids = centroids.float()
    np.save(
        destination_path_obj / "centroids.npy",
        centroids.numpy(force=True).astype(np.float32),
    )

    ivf, ivf_lengths = torch.load(index_path_obj / "ivf.pid.pt")
    if ivf_lengths.shape != (num_partitions,):
        msg = f"ivf_lengths.shape must be ({num_partitions},), got {ivf_lengths.shape}"
        raise ValueError(msg)
    if ivf.shape != (ivf_lengths.sum(),):
        msg = f"ivf.shape must be ({ivf_lengths.sum()},), got {ivf.shape}"
        raise ValueError(msg)

    centroid_sizes = torch.zeros((num_partitions,), dtype=torch.int64)
    for chunk in tqdm(range(num_chunks)):
        # NOTE codes describe the corresponding centroid for each embedding
        codes = torch.load(index_path_obj / f"{chunk}.codes.pt")
        centroid_sizes += torch.bincount(codes, minlength=num_partitions)
    num_residuals = centroid_sizes.sum().item()

    offsets = torch.zeros((num_partitions,), dtype=torch.int64)
    offsets[1:] = torch.cumsum(centroid_sizes[:-1], dim=0)

    residual_dim = (dim * nbits) // 8  # residuals are stored as uint8

    tensor_offsets = torch.zeros((num_partitions,), dtype=torch.int64)
    tensor_offsets[1:] = torch.cumsum(centroid_sizes[:-1], dim=0)

    tensor_offsets = torch.zeros((num_partitions,), dtype=torch.int64)
    tensor_offsets[1:] = torch.cumsum(centroid_sizes[:-1], dim=0)

    tensor_compacted_residuals = torch.zeros((num_residuals, residual_dim), dtype=torch.uint8)
    tensor_compacted_codes = torch.zeros((num_residuals,), dtype=torch.int32)

    passage_id = 0
    for chunk in tqdm(range(num_chunks)):
        with (index_path_obj / f"doclens.{chunk}.json").open(encoding="utf-8") as file:
            doclens = json.load(file)
        codes = torch.load(index_path_obj / f"{chunk}.codes.pt")
        residuals = torch.load(index_path_obj / f"{chunk}.residuals.pt")

        doclens = torch.tensor(doclens)
        if doclens.sum() != residuals.shape[0]:
            msg = (
                f"doclens.sum() ({doclens.sum()}) must equal "
                f"residuals.shape[0] ({residuals.shape[0]})"
            )
            raise ValueError(msg)

        passage_ids = (
            torch.repeat_interleave(torch.arange(doclens.shape[0]), doclens).int() + passage_id
        )

        tensor_idx, tensor_offsets = segmented_index_cumsum(codes, tensor_offsets)

        tensor_compacted_residuals[tensor_idx] = residuals
        tensor_compacted_codes[tensor_idx] = passage_ids

        passage_id += doclens.shape[0]

    torch.save(
        centroid_sizes,
        destination_path_obj / "sizes.compacted.pt",
    )
    torch.save(
        tensor_compacted_residuals,
        destination_path_obj / "residuals.compacted.pt",
    )
    torch.save(
        tensor_compacted_codes,
        destination_path_obj / "codes.compacted.pt",
    )

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
    reversed_bit_map = torch.tensor(reversed_bit_map).to(torch.uint8)

    # A table of all possible lookup orders into bucket_weights
    # given n bits per lookup
    keys_per_byte = 8 // nbits
    decompression_lookup_table = torch.tensor(
        list(product(list(range(len(bucket_weights))), repeat=keys_per_byte))
    ).to(torch.uint8)

    residuals_repacked_compacted = reversed_bit_map[tensor_compacted_residuals.long()]
    residuals_repacked_compacted_d = decompression_lookup_table[residuals_repacked_compacted.long()]
    # NOTE This could easily be generalized to arbitrary powers of two.
    if nbits == NBITS_4:
        residuals_repacked_compacted_df = (
            2**4 * residuals_repacked_compacted_d[:, :, 0] + residuals_repacked_compacted_d[:, :, 1]
        )
    elif nbits == NBITS_2:
        residuals_repacked_compacted_df = (
            2**6 * residuals_repacked_compacted_d[:, :, 0]
            + 2**4 * residuals_repacked_compacted_d[:, :, 1]
            + 2**2 * residuals_repacked_compacted_d[:, :, 2]
            + residuals_repacked_compacted_d[:, :, 3]
        )
    else:
        raise AssertionError
    torch.save(
        residuals_repacked_compacted_df,
        destination_path_obj / "residuals.repacked.compacted.pt",
    )
