"""Index storage and scoring for WARP search.

This module provides IndexScorer, combining index loading and candidate
generation with scoring capabilities for end-to-end retrieval and ranking.
"""

from __future__ import annotations

import os
import pathlib
from collections.abc import Callable
from dataclasses import dataclass
from math import ceil

import torch
from torch.utils.cpp_extension import load
from warp.indexing.codecs.residual_embeddings_strided import ResidualEmbeddingsStrided
from warp.infra.config.config import ColBERTConfig
from warp.modeling.colbert import (
    colbert_score,
    colbert_score_packed,
    colbert_score_reduce,
)
from warp.search.candidate_generation import CandidateGeneration
from warp.search.index_loader import IndexLoader
from warp.search.strided_tensor import StridedTensor
from warp.utils.tracker import DEFAULT_NOP_TRACKER, Tracker
from warp.utils.utils import print_message


@dataclass(frozen=True)
class ScoreBatch:
    """Batch of query and document embeddings for scoring."""

    q: torch.Tensor
    d_packed: torch.Tensor
    d_mask: torch.Tensor
    pids: torch.Tensor


class IndexScorer(IndexLoader, CandidateGeneration):
    """Index scorer combining loading, candidate generation, and ranking.

    Extends IndexLoader and CandidateGeneration with scoring methods for
    end-to-end retrieval and ranking. Supports GPU-accelerated scoring
    with custom filtering and tracking.

    Parameters
    ----------
    index_path : str | pathlib.Path
        Path to index directory.
    use_gpu : bool
        Whether to use GPU acceleration (default: True).
    load_index_with_mmap : bool
        Whether to load index with memory mapping (default: False).
    """

    def __init__(
        self,
        index_path: str | pathlib.Path,
        *,
        use_gpu: bool = True,
        load_index_with_mmap: bool = False,
    ) -> None:
        super().__init__(
            index_path=index_path,
            use_gpu=use_gpu,
            load_index_with_mmap=load_index_with_mmap,
        )

        IndexScorer.try_load_torch_extensions(use_gpu=use_gpu)

        self.set_embeddings_strided()

    @classmethod
    def try_load_torch_extensions(cls, *, use_gpu: bool) -> None:
        """Load CUDA extensions for GPU-accelerated scoring.

        Loads filter_pids_cpp and decompress_residuals_cpp extensions if GPU
        is available and extensions haven't been loaded yet.

        Parameters
        ----------
        use_gpu : bool
            Whether to attempt loading GPU extensions.
        """
        if hasattr(cls, "loaded_extensions") or use_gpu:
            return

        print_message(
            "Loading filter_pids_cpp extension "
            "(set COLBERT_LOAD_TORCH_EXTENSION_VERBOSE=True for more info)..."
        )
        filter_pids_cpp = load(
            name="filter_pids_cpp",
            sources=[
                str(pathlib.Path(__file__).parent.resolve() / "filter_pids.cpp"),
            ],
            extra_cflags=["-O3"],
            verbose=os.getenv("COLBERT_LOAD_TORCH_EXTENSION_VERBOSE", "False")
            == "True",
        )
        cls.filter_pids = filter_pids_cpp.filter_pids_cpp

        print_message(
            "Loading decompress_residuals_cpp extension "
            "(set COLBERT_LOAD_TORCH_EXTENSION_VERBOSE=True for more info)..."
        )
        decompress_residuals_cpp = load(
            name="decompress_residuals_cpp",
            sources=[
                str(
                    pathlib.Path(__file__).parent.resolve() / "decompress_residuals.cpp"
                ),
            ],
            extra_cflags=["-O3"],
            verbose=os.getenv("COLBERT_LOAD_TORCH_EXTENSION_VERBOSE", "False")
            == "True",
        )
        cls.decompress_residuals = decompress_residuals_cpp.decompress_residuals_cpp

        cls.loaded_extensions = True

    def set_embeddings_strided(self) -> None:
        """Initialize strided embeddings wrapper.

        Sets up ResidualEmbeddingsStrided for efficient passage-level lookup.
        Uses memory-mapped offsets if load_index_with_mmap is True.

        Raises
        ------
        ValueError
            If num_chunks != 1 when load_index_with_mmap=True.
        """
        if self.load_index_with_mmap:
            if self.num_chunks != 1:
                msg = f"num_chunks must be 1 when load_index_with_mmap=True, got {self.num_chunks}"
                raise ValueError(msg)
            self.offsets = torch.cumsum(self.doclens, dim=0)
            self.offsets = torch.cat((torch.zeros(1, dtype=torch.int64), self.offsets))
        else:
            self.embeddings_strided = ResidualEmbeddingsStrided(
                self.codec, self.embeddings, self.doclens
            )
            self.offsets = self.embeddings_strided.codes_strided.offsets

    def lookup_pids(
        self,
        passage_ids: torch.Tensor,
        out_device: str | torch.device = "cuda",
        *,
        _return_mask: bool = False,
    ) -> torch.Tensor | tuple[torch.Tensor, torch.Tensor]:
        """Lookup embeddings for passage IDs.

        Delegates to embeddings_strided.lookup_pids for passage-level
        embedding retrieval.

        Parameters
        ----------
        passage_ids : torch.Tensor
            Passage IDs to lookup.
        out_device : str | torch.device
            Device for output tensors (default: "cuda").

        Returns
        -------
        torch.Tensor
            Embeddings tensor.
        """
        return self.embeddings_strided.lookup_pids(passage_ids, out_device)

    def retrieve(
        self, config: ColBERTConfig, q: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Retrieve candidate passage IDs for queries.

        Generates candidates using query embeddings truncated to query_maxlen.

        Parameters
        ----------
        config : ColBERTConfig
            Configuration specifying query_maxlen and ncells.
        q : torch.Tensor
            Query embeddings (num_queries x seq_len x dim).

        Returns
        -------
        tuple[torch.Tensor, torch.Tensor]
            Tuple of (passage_ids, centroid_scores).
        """
        q = q[
            :, : config.query_maxlen
        ]  # NOTE: Candidate generation uses only the query tokens
        pids, centroid_scores = self.generate_candidates(config, q)

        return pids, centroid_scores

    def embedding_ids_to_pids(self, embedding_ids: torch.Tensor) -> torch.Tensor:
        """Convert embedding IDs to unique passage IDs.

        Maps embedding IDs to passage IDs and returns unique values.

        Parameters
        ----------
        embedding_ids : torch.Tensor
            Embedding IDs to convert.

        Returns
        -------
        torch.Tensor
            Unique passage IDs.
        """
        return torch.unique(self.emb2pid[embedding_ids.long()].cuda(), sorted=False)

    def rank(
        self,
        config: ColBERTConfig,
        q: torch.Tensor,
        filter_fn: Callable[[torch.Tensor], torch.Tensor] | None = None,
        pids: list[int] | torch.Tensor | None = None,
        tracker: Tracker = DEFAULT_NOP_TRACKER,
    ) -> tuple[list[int], list[float]]:
        """Rank passages for queries.

        Generates candidates (or uses provided pids), optionally filters,
        scores passages, and returns sorted results.

        Parameters
        ----------
        config : ColBERTConfig
            Configuration for retrieval and scoring.
        q : torch.Tensor
            Query embeddings (1 x num_queries x dim or num_queries x dim).
        filter_fn : Callable[[torch.Tensor], torch.Tensor] | None
            Optional function to filter passage IDs (default: None).
        pids : list[int] | torch.Tensor | None
            Optional pre-computed passage IDs (default: None).
        tracker : Tracker
            Performance tracker (default: NOPTracker()).

        Returns
        -------
        tuple[list[int], list[float]]
            Tuple of (sorted_passage_ids, sorted_scores).

        Raises
        ------
        TypeError
            If filter_fn returns non-Tensor.
        ValueError
            If filtered_pids dtype/device mismatch with pids.
        """
        with torch.inference_mode():
            tracker.begin("Candidate Generation")
            if pids is None:
                pids, centroid_scores = self.retrieve(config, q)
            else:
                pids_, centroid_scores = self.retrieve(config, q)
                pids = torch.tensor(pids, dtype=pids_.dtype, device=pids_.device)
            tracker.end("Candidate Generation")

            if filter_fn is not None:
                filtered_pids = filter_fn(pids)
                if not isinstance(filtered_pids, torch.Tensor):
                    msg = f"filter_fn must return torch.Tensor, got {type(filtered_pids).__name__}"
                    raise TypeError(msg)
                if filtered_pids.dtype != pids.dtype:
                    msg = (
                        f"filtered_pids.dtype ({filtered_pids.dtype}) must equal "
                        f"pids.dtype ({pids.dtype})"
                    )
                    raise ValueError(msg)
                if filtered_pids.device != pids.device:
                    msg = (
                        f"filtered_pids.device ({filtered_pids.device}) "
                        f"must equal pids.device ({pids.device})"
                    )
                    raise ValueError(msg)
                pids = filtered_pids
                if len(pids) == 0:
                    return [], []

            scores, pids = self.score_pids(
                config, q, pids, centroid_scores, tracker=tracker
            )

            tracker.begin("Sorting")
            scores_sorter = scores.sort(descending=True)
            pids, scores = (
                pids[scores_sorter.indices].tolist(),
                scores_sorter.values.tolist(),
            )
            tracker.end("Sorting")

            return pids, scores

    def score_pids(
        self,
        config: ColBERTConfig,
        q: torch.Tensor,
        pids: torch.Tensor,
        centroid_scores: torch.Tensor,
        tracker: Tracker = DEFAULT_NOP_TRACKER,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Score query-passage pairs using ColBERT similarity.

        Computes ColBERT scores for query-passage pairs, processing in batches.
        Always supply a flat list or tensor for `pids`.

        Parameters
        ----------
        config : ColBERTConfig
            Configuration for scoring.
        q : torch.Tensor
            Query embeddings (1 | num_docs, *, dim). If q.size(0) is 1,
            compares with all passages. Otherwise, each query is compared
            against the aligned passage.
        pids : torch.Tensor
            Flat passage IDs to score.
        centroid_scores : torch.Tensor
            Pre-computed centroid scores.
        tracker : Tracker
            Performance tracker (default: NOPTracker()).

        Returns
        -------
        tuple[torch.Tensor, torch.Tensor]
            Tuple of (scores, pids).

        Notes
        -----
        This function may raise ValueError if filtered_pids dtype or device doesn't match
        pids, or if approx_scores is not on CUDA device when required. The exception is
        raised indirectly by internal validation helpers or tensor operations when
        device/dtype mismatches occur.

        Consider removing batching for simplification.
        """
        # NOTE: Remove batching?
        batch_size = 2**20
        if self.use_gpu:
            centroid_scores = centroid_scores.cuda()

        idx = centroid_scores.max(-1).values >= config.centroid_score_threshold

        tracker.begin("Filtering")
        if self.use_gpu:
            pids = self._filter_gpu_pids(config, pids, centroid_scores, idx, batch_size)
        else:
            pids = self._filter_cpu_pids(config, pids, centroid_scores, idx)
        tracker.end("Filtering")

        tracker.begin("Decompress Residuals")
        d_packed, d_mask = self._decompress_residuals(pids)
        tracker.end("Decompress Residuals")

        batch = ScoreBatch(q=q, d_packed=d_packed, d_mask=d_mask, pids=pids)
        if q.size(0) == 1:
            return self._score_single_query(batch, config, tracker)

        return self._score_multi_query(batch, config, tracker)

    def _filter_gpu_pids(
        self,
        config: ColBERTConfig,
        pids: torch.Tensor,
        centroid_scores: torch.Tensor,
        idx: torch.Tensor,
        batch_size: int,
    ) -> torch.Tensor:
        approx_scores = self._compute_gpu_pruned_scores(
            pids, idx, centroid_scores, batch_size, config
        )
        if not approx_scores.is_cuda:
            msg = f"approx_scores must be on CUDA device, got {approx_scores.device}"
            raise ValueError(msg)
        if config.ndocs < len(approx_scores):
            pids = pids[torch.topk(approx_scores, k=config.ndocs).indices]

        codes_packed, codes_lengths = self.embeddings_strided.lookup_codes(pids)
        approx_scores = centroid_scores[codes_packed.long()]
        approx_scores = self._score_pruned_codes(approx_scores, codes_lengths, config)
        ndocs_cutoff = config.ndocs // 4
        if ndocs_cutoff < len(approx_scores):
            pids = pids[torch.topk(approx_scores, k=ndocs_cutoff).indices]
        return pids

    def _compute_gpu_pruned_scores(
        self,
        pids: torch.Tensor,
        idx: torch.Tensor,
        centroid_scores: torch.Tensor,
        batch_size: int,
        config: ColBERTConfig,
    ) -> torch.Tensor:
        approx_scores: list[torch.Tensor] = []
        for i in range(ceil(len(pids) / batch_size)):
            pids_ = pids[i * batch_size : (i + 1) * batch_size]
            codes_packed, codes_lengths = self.embeddings_strided.lookup_codes(pids_)
            idx_ = idx[codes_packed.long()]
            pruned_codes_strided = StridedTensor(
                idx_, codes_lengths, use_gpu=self.use_gpu
            )
            pruned_codes_padded, pruned_codes_mask = (
                pruned_codes_strided.as_padded_tensor()
            )
            pruned_codes_lengths = (pruned_codes_padded * pruned_codes_mask).sum(dim=1)
            codes_packed_ = codes_packed[idx_]
            approx_scores_ = centroid_scores[codes_packed_.long()]
            if approx_scores_.shape[0] == 0:
                approx_scores.append(
                    torch.zeros((len(pids_),), dtype=approx_scores_.dtype).cuda()
                )
                continue
            approx_scores_strided = StridedTensor(
                approx_scores_, pruned_codes_lengths, use_gpu=self.use_gpu
            )
            approx_scores_padded, approx_scores_mask = (
                approx_scores_strided.as_padded_tensor()
            )
            approx_scores_ = colbert_score_reduce(
                approx_scores_padded, approx_scores_mask, config
            )
            approx_scores.append(approx_scores_)
        return torch.cat(approx_scores, dim=0)

    def _score_pruned_codes(
        self,
        approx_scores: torch.Tensor,
        codes_lengths: torch.Tensor,
        config: ColBERTConfig,
    ) -> torch.Tensor:
        approx_scores_strided = StridedTensor(
            approx_scores, codes_lengths, use_gpu=self.use_gpu
        )
        approx_scores_padded, approx_scores_mask = (
            approx_scores_strided.as_padded_tensor()
        )
        return colbert_score_reduce(approx_scores_padded, approx_scores_mask, config)

    def _filter_cpu_pids(
        self,
        config: ColBERTConfig,
        pids: torch.Tensor,
        centroid_scores: torch.Tensor,
        idx: torch.Tensor,
    ) -> torch.Tensor:
        return IndexScorer.filter_pids(
            pids,
            centroid_scores,
            self.embeddings.codes,
            self.doclens,
            self.offsets,
            idx,
            config.ndocs,
        )

    def _decompress_residuals(
        self, pids: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        if self.use_gpu:
            return self.lookup_pids(pids)

        d_packed = IndexScorer.decompress_residuals(
            pids,
            self.doclens,
            self.offsets,
            self.codec.bucket_weights,
            self.codec.reversed_bit_map,
            self.codec.decompression_lookup_table,
            self.embeddings.residuals,
            self.embeddings.codes,
            self.codec.centroids,
            self.codec.dim,
            self.codec.nbits,
        )
        d_packed = torch.nn.functional.normalize(
            d_packed.to(torch.float32), p=2, dim=-1
        )
        d_mask = self.doclens[pids.long()]
        return d_packed, d_mask

    def _score_single_query(
        self, batch: ScoreBatch, config: ColBERTConfig, tracker: Tracker
    ) -> tuple[torch.Tensor, torch.Tensor]:
        tracker.begin("Scoring")
        scores = colbert_score_packed(batch.q, batch.d_packed, batch.d_mask, config)
        scores = self._normalize_scores(scores, batch.q, config)
        tracker.end("Scoring")
        return scores, batch.pids

    def _score_multi_query(
        self, batch: ScoreBatch, config: ColBERTConfig, tracker: Tracker
    ) -> tuple[torch.Tensor, torch.Tensor]:
        tracker.begin("Scoring")
        d_strided = StridedTensor(batch.d_packed, batch.d_mask, use_gpu=self.use_gpu)
        d_padded, d_lengths = d_strided.as_padded_tensor()
        scores = colbert_score(batch.q, d_padded, d_lengths, config)
        scores = self._normalize_scores(scores, batch.q, config)
        tracker.end("Scoring")
        return scores, batch.pids

    @staticmethod
    def _normalize_scores(
        scores: torch.Tensor, q: torch.Tensor, config: ColBERTConfig
    ) -> torch.Tensor:
        if config.checkpoint == "google/xtr-base-en":
            query_len = q.count_nonzero(dim=1)[0, 0]
            scores /= query_len
        return scores
