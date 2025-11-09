"""Index optimization utilities for WARP indices.

This module provides functions for optimizing IVF (Inverted File) structures
to improve search efficiency by mapping centroids directly to passage IDs.
"""

from __future__ import annotations

import pathlib

import torch
import tqdm
from warp.indexing.loaders import load_doclens
from warp.utils.utils import flatten, print_message


def optimize_ivf(
    orig_ivf: torch.Tensor,
    orig_ivf_lengths: torch.Tensor,
    index_path: str | pathlib.Path,
    verbose: int = 3,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Optimize IVF structure to map centroids to passage IDs.

    Converts an IVF structure that maps centroids to embedding indices into
    one that maps centroids directly to passage IDs. This optimization reduces
    lookup overhead during search by eliminating the embedding-to-passage mapping.

    Parameters
    ----------
    orig_ivf : torch.Tensor
        Original IVF tensor mapping centroids to embedding indices.
    orig_ivf_lengths : torch.Tensor
        Lengths of lists for each centroid in orig_ivf.
    index_path : str
        Path to index directory containing doclens files.
    verbose : int
        Verbosity level (default: 3).

    Returns
    -------
    tuple[torch.Tensor, torch.Tensor]
        Tuple of (optimized_ivf, optimized_ivf_lengths) mapping centroids to passage IDs.
    """
    if verbose > 1:
        print_message("#> Optimizing IVF to store map from centroids to list of pids..")

        print_message("#> Building the emb2pid mapping..")
    all_doclens = load_doclens(index_path, flatten=False)

    all_doclens = flatten(all_doclens)
    total_num_embeddings = sum(all_doclens)

    emb2pid = torch.zeros(total_num_embeddings, dtype=torch.int)

    """
    EVENTUALLY: Use two tensors. emb2pid_offsets will have every 256th element.
    emb2pid_delta will have the delta from the corresponding offset,
    """

    offset_doclens = 0
    for pid, dlength in enumerate(all_doclens):
        emb2pid[offset_doclens : offset_doclens + dlength] = pid
        offset_doclens += dlength

    if verbose > 1:
        print_message("len(emb2pid) =", len(emb2pid))

    ivf = emb2pid[orig_ivf]
    unique_pids_per_centroid = []
    ivf_lengths = []

    offset = 0
    for length in tqdm.tqdm(orig_ivf_lengths.tolist()):
        pids = torch.unique(ivf[offset : offset + length])
        unique_pids_per_centroid.append(pids)
        ivf_lengths.append(pids.shape[0])
        offset += length
    ivf = torch.cat(unique_pids_per_centroid)
    ivf_lengths = torch.tensor(ivf_lengths)

    index_path_obj = pathlib.Path(index_path)
    original_ivf_path = index_path_obj / "ivf.pt"
    optimized_ivf_path = index_path_obj / "ivf.pid.pt"
    torch.save((ivf, ivf_lengths), optimized_ivf_path)
    if verbose > 1:
        print_message(f"#> Saved optimized IVF to {optimized_ivf_path}")
        if pathlib.Path(original_ivf_path).exists():
            print_message(f'#> Original IVF at path "{original_ivf_path}" can now be removed')

    return ivf, ivf_lengths
