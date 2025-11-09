"""Candidate generation for WARP search.

This module provides CandidateGeneration for generating candidate passages
using IVF (Inverted File) index lookup based on query embeddings.
"""

from __future__ import annotations

import torch
from warp.infra.config.config import ColBERTConfig
from warp.search.strided_tensor import StridedTensor

# Expected tensor dimension for packed queries
EXPECTED_PACKED_QUERY_DIM = 2


class CandidateGeneration:
    """Generate candidate passages for query search.

    Uses IVF index to lookup passages based on query-centroid similarity.
    Supports GPU acceleration and flexible candidate generation strategies.

    Parameters
    ----------
    use_gpu : bool
        Whether to use GPU acceleration (default: True).
    """

    def __init__(self, *, use_gpu: bool = True) -> None:
        """Initialize CandidateGeneration with GPU preference.

        Parameters
        ----------
        use_gpu : bool
            Whether to use GPU acceleration (default: True).
        """
        self.use_gpu = use_gpu

    def get_cells(self, q: torch.Tensor, ncells: int) -> tuple[torch.Tensor, torch.Tensor]:
        """Get top-k centroid cells for query embeddings.

        Computes query-centroid similarity scores and returns top-k cell
        indices for each query token.

        Parameters
        ----------
        q : torch.Tensor
            Query embeddings (num_queries x dim).
        ncells : int
            Number of top cells to retrieve per query.

        Returns
        -------
        tuple[torch.Tensor, torch.Tensor]
            Tuple of (unique_cell_indices, centroid_scores).
        """
        scores = self.codec.centroids @ q.T
        if ncells == 1:
            cells = scores.argmax(dim=0, keepdim=True).permute(1, 0)
        else:
            cells = scores.topk(ncells, dim=0, sorted=False).indices.permute(1, 0)  # (32, ncells)
        cells = cells.flatten().contiguous()  # (32 * ncells,)
        cells = cells.unique(sorted=False)
        return cells, scores

    def generate_candidate_eids(
        self, q: torch.Tensor, ncells: int
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Generate candidate embedding IDs for queries.

        Looks up embedding IDs from IVF index using top-k cells.

        Parameters
        ----------
        q : torch.Tensor
            Query embeddings (num_queries x dim).
        ncells : int
            Number of cells to use for lookup.

        Returns
        -------
        tuple[torch.Tensor, torch.Tensor]
            Tuple of (embedding_ids, centroid_scores).
        """
        cells, scores = self.get_cells(q, ncells)

        eids, _cell_lengths = self.ivf.lookup(
            cells
        )  # eids = (packedlen,)  lengths = (32 * ncells,)
        eids = eids.long()
        if self.use_gpu:
            eids = eids.cuda()
        return eids, scores

    def generate_candidate_pids(
        self, q: torch.Tensor, ncells: int
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Generate candidate passage IDs for queries.

        Looks up passage IDs from IVF index using top-k cells.

        Parameters
        ----------
        q : torch.Tensor
            Query embeddings (num_queries x dim).
        ncells : int
            Number of cells to use for lookup.

        Returns
        -------
        tuple[torch.Tensor, torch.Tensor]
            Tuple of (passage_ids, centroid_scores).
        """
        cells, scores = self.get_cells(q, ncells)

        pids, _cell_lengths = self.ivf.lookup(cells)
        if self.use_gpu:
            pids = pids.cuda()
        return pids, scores

    def generate_candidate_scores(self, q: torch.Tensor, eids: torch.Tensor) -> torch.Tensor:
        """Generate similarity scores for query-embedding pairs.

        Computes dot product scores between query and candidate embeddings.

        Parameters
        ----------
        q : torch.Tensor
            Query embeddings (num_queries x dim).
        eids : torch.Tensor
            Embedding IDs to score.

        Returns
        -------
        torch.Tensor
            Similarity scores (num_queries x num_candidates).
        """
        e = self.lookup_eids(eids)
        if self.use_gpu:
            e = e.cuda()
        return (q.unsqueeze(0) @ e.unsqueeze(2)).squeeze(-1).T

    def generate_candidates(
        self, config: ColBERTConfig, q: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Generate unique candidate passage IDs for queries.

        Generates candidates, deduplicates, and returns sorted unique
        passage IDs with centroid scores.

        Parameters
        ----------
        config : ColBERTConfig
            Configuration specifying ncells parameter.
        q : torch.Tensor
            Query embeddings (1 x num_queries x dim or num_queries x dim).

        Returns
        -------
        tuple[torch.Tensor, torch.Tensor]
            Tuple of (unique_passage_ids, centroid_scores).

        Raises
        ------
        TypeError
            If self.ivf is not a StridedTensor.
        ValueError
            If q.dim() is not 2 after squeezing.
        """
        ncells = config.ncells

        if not isinstance(self.ivf, StridedTensor):
            msg = f"self.ivf must be StridedTensor, got {type(self.ivf).__name__}"
            raise TypeError(msg)

        q = q.squeeze(0)
        if self.use_gpu:
            q = q.cuda()
        if q.dim() != EXPECTED_PACKED_QUERY_DIM:
            msg = f"q.dim() must be {EXPECTED_PACKED_QUERY_DIM}, got {q.dim()}"
            raise ValueError(msg)

        pids, centroid_scores = self.generate_candidate_pids(q, ncells)

        sorter = pids.sort()
        pids = sorter.values

        pids, pids_counts = torch.unique_consecutive(pids, return_counts=True)
        if self.use_gpu:
            pids, pids_counts = pids.cuda(), pids_counts.cuda()

        return pids, centroid_scores
