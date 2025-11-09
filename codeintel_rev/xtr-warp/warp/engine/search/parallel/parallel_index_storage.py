"""Parallel WARP-specific index loading and scoring.

This module provides ParallelIndexLoaderWARP and ParallelIndexScorerWARP
for parallel CPU execution with WARP-specific index formats.
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass

import numpy as np
import torch
from torch.utils.cpp_extension import load
from warp.engine.constants import T_PRIME_MAX, TPrimePolicy
from warp.engine.search.index_storage import IndexScorerOptions
from warp.infra.config.config import ColBERTConfig
from warp.utils.tracker import DEFAULT_NOP_TRACKER, NOPTracker
from warp.utils.utils import print_message


class ParallelIndexLoaderWARP:
    """Parallel WARP-specific index loader.

    Loads WARP-compacted index format with bucket weights, centroids,
    codes, and residuals. CPU-only parallel execution (use_gpu must be False).

    Parameters
    ----------
    index_path : str
        Path to index directory.
    config : ColBERTConfig
        Configuration for index loading.
    use_gpu : bool
        Whether to use GPU (must be False, default: True).
    load_index_with_mmap : bool
        Whether to use memory mapping (must be False, default: False).
    fused_decompression_merge : bool
        Whether to use fused decompression-merge (default: True).

    Raises
    ------
    ValueError
        If use_gpu=True or load_index_with_mmap=True.
    """

    def __init__(
        self,
        index_path: str,
        _config: ColBERTConfig,
        *,
        use_gpu: bool = True,
        load_index_with_mmap: bool = False,
        fused_decompression_merge: bool = True,
    ) -> None:
        if use_gpu:
            msg = "use_gpu must be False for ParallelIndexLoaderWARP"
            raise ValueError(msg)
        if load_index_with_mmap:
            msg = "load_index_with_mmap must be False for ParallelIndexLoaderWARP"
            raise ValueError(msg)

        self.index_path = index_path
        self.use_gpu = use_gpu
        self.load_index_with_mmap = load_index_with_mmap
        self.fused_decompression_merge = fused_decompression_merge

        print_message("#> Loading buckets...")
        index_path_obj = pathlib.Path(self.index_path)
        bucket_weights = torch.from_numpy(
            np.load(index_path_obj / "bucket_weights.npy")
        )
        self.bucket_weights = bucket_weights

        self._load_codec()
        print_message("#> Loading repacked residuals...")
        self.residuals_compacted = torch.load(
            index_path_obj / "residuals.repacked.compacted.pt"
        )

    def _load_codec(self) -> torch.Tensor:
        print_message("#> Loading codec...")

        index_path_obj = pathlib.Path(self.index_path)
        centroids = torch.from_numpy(np.load(index_path_obj / "centroids.npy"))
        sizes_compacted = torch.load(index_path_obj / "sizes.compacted.pt")
        codes_compacted = torch.load(index_path_obj / "codes.compacted.pt")

        residuals_compacted = torch.load(index_path_obj / "residuals.compacted.pt")

        num_centroids = centroids.shape[0]
        if sizes_compacted.shape != (num_centroids,):
            msg = f"sizes_compacted.shape must be ({num_centroids},), got {sizes_compacted.shape}"
            raise ValueError(msg)

        num_embeddings = residuals_compacted.shape[0]
        if sizes_compacted.sum() != num_embeddings:
            msg = (
                f"sizes_compacted.sum() ({sizes_compacted.sum()}) must equal "
                f"num_embeddings ({num_embeddings})"
            )
            raise ValueError(msg)
        if codes_compacted.shape != (num_embeddings,):
            msg = f"codes_compacted.shape must be ({num_embeddings},), got {codes_compacted.shape}"
            raise ValueError(msg)

        self.sizes_compacted = sizes_compacted
        self.codes_compacted = codes_compacted

        offsets_compacted = torch.zeros((num_centroids + 1,), dtype=torch.long)
        torch.cumsum(sizes_compacted, dim=0, out=offsets_compacted[1:])
        self.offsets_compacted = offsets_compacted

        self.kdummy_centroid = sizes_compacted.argmin().item()

        self.centroids = centroids

        return residuals_compacted


@dataclass(frozen=True)
class ParallelIndexScorerOptions(IndexScorerOptions):
    """Options for parallel WARP index scorer with fused decompression-merge."""

    fused_decompression_merge: bool = True


@dataclass(frozen=True)
class ParallelCandidateBatch:
    """Batch of candidate results for parallel processing."""

    capacities: torch.Tensor
    sizes: torch.Tensor
    pids: torch.Tensor
    scores: torch.Tensor


@dataclass(frozen=True)
class MergeParams:
    """Parameters for merging candidate scores in parallel processing."""

    nprobe: int
    num_tokens: int
    mse_estimates: torch.Tensor
    k: int


class ParallelIndexScorerWARP(ParallelIndexLoaderWARP):
    """Parallel WARP-specific index scorer.

    Extends ParallelIndexLoaderWARP with parallel scoring capabilities using
    WARP-specific compression and candidate selection. CPU-only parallel execution
    (use_gpu must be False, num_threads must be > 1).

    Parameters
    ----------
    index_path : str
        Path to index directory.
    config : ColBERTConfig
        Configuration for scoring (ncells must be set, nbits must be 2 or 4).
    use_gpu : bool
        Whether to use GPU (must be False, default: False).
    load_index_with_mmap : bool
        Whether to use memory mapping (must be False, default: False).
    t_prime : int | None
        T' policy value (default: None, auto-computed).
    bound : int
        Score bound (default: 128).
    fused_decompression_merge : bool
        Whether to use fused decompression-merge (default: True).

    Raises
    ------
    ValueError
        If use_gpu=True, load_index_with_mmap=True, num_threads=1,
        config.ncells is None, or config.nbits not in {2, 4}.
    """

    def __init__(
        self,
        index_path: str,
        config: ColBERTConfig,
        *,
        options: ParallelIndexScorerOptions | None = None,
    ) -> None:
        opts = options or ParallelIndexScorerOptions()
        if opts.use_gpu:
            msg = "use_gpu must be False for ParallelIndexScorerWARP"
            raise ValueError(msg)
        if opts.load_index_with_mmap:
            msg = "load_index_with_mmap must be False for ParallelIndexScorerWARP"
            raise ValueError(msg)

        super().__init__(
            index_path=index_path,
            config=config,
            use_gpu=opts.use_gpu,
            load_index_with_mmap=opts.load_index_with_mmap,
            fused_decompression_merge=opts.fused_decompression_merge,
        )

        num_threads = torch.get_num_threads()
        if num_threads == 1:
            msg = "num_threads must be > 1 for parallel execution"
            raise ValueError(msg)

        ParallelIndexScorerWARP.try_load_torch_extensions(use_gpu=opts.use_gpu)

        if config.ncells is None:
            msg = "config.ncells must be set"
            raise ValueError(msg)
        self.nprobe = config.ncells

        (num_centroids, _) = self.centroids.shape
        if opts.t_prime is not None:
            self.t_prime = TPrimePolicy(value=opts.t_prime)
        elif num_centroids <= 2**16:
            (num_embeddings, _) = self.residuals_compacted.shape
            self.t_prime = TPrimePolicy(
                value=int(np.sqrt(8 * num_embeddings) / 1000) * 1000
            )
        else:
            self.t_prime = T_PRIME_MAX

        if config.nbits not in {2, 4}:
            msg = f"config.nbits must be 2 or 4, got {config.nbits}"
            raise ValueError(msg)
        self.nbits = config.nbits

        self.centroid_idx = torch.stack(
            tuple(
                torch.arange(num_centroids, dtype=torch.int32)
                for _ in range(num_threads)
            )
        ).contiguous()

        self.bound = opts.bound or 128

    @classmethod
    def try_load_torch_extensions(cls, *, use_gpu: bool) -> None:
        """Load CUDA extensions for parallel WARP scoring.

        Loads parallel_warp_select_centroids_cpp, parallel_decompress_centroids_cpp,
        parallel_merge_candidate_scores_cpp, and parallel_fused_decompress_merge_cpp
        extensions if GPU is available and extensions haven't been loaded yet.

        Parameters
        ----------
        use_gpu : bool
            Whether to attempt loading GPU extensions.
        """
        if hasattr(cls, "loaded_extensions") or use_gpu:
            return
        cflags = [
            "-O3",
            "-mavx2",
            "-mfma",
            "-march=native",
            "-ffast-math",
            "-fno-math-errno",
            "-m64",
            "-fopenmp",
            "-std=c++17",
            "-funroll-loops",
            "-msse",
            "-msse2",
            "-msse3",
            "-msse4.1",
            "-mbmi2",
            "-mmmx",
            "-mavx",
            "-fomit-frame-pointer",
            "-fno-strict-aliasing",
        ]

        print_message(
            "Loading parallel_warp_select_centroids_cpp extension "
            "(set WARP_LOAD_TORCH_EXTENSION_VERBOSE=True for more info)..."
        )
        cls.warp_select_centroids_cpp = load(
            name="parallel_warp_select_centroids_cpp",
            sources=[
                str(
                    pathlib.Path(__file__).parent.resolve()
                    / "parallel_warp_select_centroids.cpp"
                ),
            ],
            extra_cflags=cflags,
            verbose=os.getenv("WARP_LOAD_TORCH_EXTENSION_VERBOSE", "False") == "True",
        ).parallel_warp_select_centroids_cpp

        print_message(
            "Loading parallel_decompress_centroids_cpp extension "
            "(set WARP_LOAD_TORCH_EXTENSION_VERBOSE=True for more info)..."
        )
        cls.decompress_centroids_cpp = {}
        decompress_centroids_cpp = load(
            name="parallel_decompress_centroids_cpp",
            sources=[
                str(
                    pathlib.Path(__file__).parent.resolve()
                    / "parallel_decompress_centroids.cpp"
                ),
            ],
            extra_cflags=cflags,
            verbose=os.getenv("WARP_LOAD_TORCH_EXTENSION_VERBOSE", "False") == "True",
        )
        cls.decompress_centroids_cpp[2] = (
            decompress_centroids_cpp.parallel_decompress_centroids_2_cpp
        )
        cls.decompress_centroids_cpp[4] = (
            decompress_centroids_cpp.parallel_decompress_centroids_4_cpp
        )

        print_message(
            "Loading parallel_merge_candidate_scores_cpp extension "
            "(set WARP_LOAD_TORCH_EXTENSION_VERBOSE=True for more info)..."
        )
        cls.merge_candidate_scores_cpp = load(
            name="parallel_merge_candidate_scores_cpp",
            sources=[
                str(
                    pathlib.Path(__file__).parent.resolve()
                    / "parallel_merge_candidate_scores.cpp"
                ),
            ],
            extra_cflags=cflags,
            verbose=os.getenv("WARP_LOAD_TORCH_EXTENSION_VERBOSE", "False") == "True",
        ).parallel_merge_candidate_scores_cpp

        print_message(
            "Loading parallel_fused_decompress_merge extension "
            "(set WARP_LOAD_TORCH_EXTENSION_VERBOSE=True for more info)..."
        )
        cls.fused_decompress_merge_cpp = {}
        fused_decompress_merge_cpp = load(
            name="parallel_fused_decompress_merge_cpp",
            sources=[
                str(
                    pathlib.Path(__file__).parent.resolve()
                    / "parallel_fused_decompress_merge.cpp"
                ),
            ],
            extra_cflags=cflags,
            verbose=os.getenv("WARP_LOAD_TORCH_EXTENSION_VERBOSE", "False") == "True",
        )
        cls.fused_decompress_merge_cpp[2] = (
            fused_decompress_merge_cpp.parallel_fused_decompress_merge_2_cpp
        )
        cls.fused_decompress_merge_cpp[4] = (
            fused_decompress_merge_cpp.parallel_fused_decompress_merge_4_cpp
        )

        cls.loaded_extensions = True

    def rank(
        self,
        _config: ColBERTConfig,
        q: torch.Tensor,
        k: int = 100,
        filter_fn: None = None,
        pids: None = None,
        tracker: NOPTracker = DEFAULT_NOP_TRACKER,
    ) -> tuple[list[int], list[float]]:
        """Rank passages for queries using parallel WARP scoring.

        Generates candidates, decompresses centroids (optionally fused with merge),
        merges scores, and returns top-k results using parallel CPU execution.

        Parameters
        ----------
        _config : ColBERTConfig
            Configuration for ranking (unused, kept for compatibility).
        q : torch.Tensor
            Query embeddings (1 x num_queries x dim or num_queries x dim).
        k : int
            Number of top results to return (default: 100).
        filter_fn : None
            Filter function (not supported, must be None).
        pids : None
            Pre-computed passage IDs (not supported, must be None).
        tracker : NOPTracker
            Performance tracker (default: NOPTracker()).

        Returns
        -------
        tuple[list[int], list[float]]
            Tuple of (sorted_passage_ids, sorted_scores).

        Raises
        ------
        ValueError
            If filter_fn or pids is not None.
        """
        if filter_fn is not None:
            msg = "filter_fn is not supported"
            raise ValueError(msg)
        if pids is not None:
            msg = "pids is not supported"
            raise ValueError(msg)

        with torch.inference_mode():
            tracker.begin("Candidate Generation")
            centroid_scores = q.squeeze(0) @ self.centroids.T
            tracker.end("Candidate Generation")

            tracker.begin("top-k Precompute")
            q_mask = q.squeeze(0).count_nonzero(dim=1) != 0
            cells, centroid_scores, mse_estimates = self._warp_select_centroids(
                q_mask, centroid_scores, self.nprobe, self.t_prime[k]
            )
            tracker.end("top-k Precompute")

            num_tokens = q_mask.sum().item()
            if self.fused_decompression_merge:
                tracker.begin("Decompression")
                tracker.end("Decompression")

                tracker.begin("Build Matrix")
                params = MergeParams(
                    nprobe=self.nprobe,
                    num_tokens=num_tokens,
                    mse_estimates=mse_estimates,
                    k=k,
                )
                pids, scores = self._fused_decompress_merge_scores(
                    q.squeeze(0), cells, centroid_scores, params
                )
                tracker.end("Build Matrix")
            else:
                tracker.begin("Decompression")
                capacities, candidate_sizes, candidate_pids, candidate_scores = (
                    self._decompress_centroids(
                        q.squeeze(0), cells, centroid_scores, self.nprobe, num_tokens
                    )
                )
                tracker.end("Decompression")

                tracker.begin("Build Matrix")
                candidate_batch = ParallelCandidateBatch(
                    capacities=capacities,
                    sizes=candidate_sizes,
                    pids=candidate_pids,
                    scores=candidate_scores,
                )
                params = MergeParams(
                    nprobe=self.nprobe,
                    num_tokens=num_tokens,
                    mse_estimates=mse_estimates,
                    k=k,
                )
                pids, scores = self._merge_candidate_scores(candidate_batch, params)
                tracker.end("Build Matrix")

            return pids, scores

    def _warp_select_centroids(
        self,
        q_mask: torch.Tensor,
        centroid_scores: torch.Tensor,
        nprobe: int,
        t_prime: int,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        cells, scores, mse = ParallelIndexScorerWARP.warp_select_centroids_cpp(
            self.centroid_idx,
            q_mask,
            centroid_scores,
            self.sizes_compacted,
            nprobe,
            t_prime,
            self.bound,
        )

        cells = cells.flatten().contiguous()
        scores = scores.flatten().contiguous()

        # NOTE Skip decompression of cells with a zero score centroid.
        # This means that the corresponding query token was 0.0 (i.e., masked out).
        cells[scores == 0] = self.kdummy_centroid

        return cells, scores, mse

    def _decompress_centroids(
        self,
        q: torch.Tensor,
        centroid_ids: torch.Tensor,
        centroid_scores: torch.Tensor,
        nprobe: int,
        num_tokens: int,
    ) -> ParallelCandidateBatch:
        centroid_ids = centroid_ids.long()
        begins = self.offsets_compacted[centroid_ids]
        ends = self.offsets_compacted[centroid_ids + 1]

        capacities = ends - begins
        sizes, pids, scores = ParallelIndexScorerWARP.decompress_centroids_cpp[
            self.nbits
        ](
            begins,
            ends,
            capacities,
            centroid_scores,
            self.codes_compacted,
            self.residuals_compacted,
            self.bucket_weights,
            q,
            nprobe,
            num_tokens,
        )
        return ParallelCandidateBatch(
            capacities=capacities, sizes=sizes, pids=pids, scores=scores
        )

    def _merge_candidate_scores(
        self, batch: ParallelCandidateBatch, params: MergeParams
    ) -> tuple[list[int], list[float]]:
        pids, scores = ParallelIndexScorerWARP.merge_candidate_scores_cpp(
            batch.capacities,
            batch.sizes,
            batch.pids,
            batch.scores,
            params.mse_estimates,
            self.nprobe,
            params.k,
            params.num_tokens,
        )
        return pids.tolist(), scores.tolist()

    def _fused_decompress_merge_scores(
        self,
        q: torch.Tensor,
        centroid_ids: torch.Tensor,
        centroid_scores: torch.Tensor,
        params: MergeParams,
    ) -> tuple[list[int], list[float]]:
        centroid_ids = centroid_ids.long()
        begins = self.offsets_compacted[centroid_ids]
        ends = self.offsets_compacted[centroid_ids + 1]

        capacities = ends - begins
        pids, scores = ParallelIndexScorerWARP.fused_decompress_merge_cpp[self.nbits](
            begins,
            ends,
            capacities,
            centroid_scores,
            self.codes_compacted,
            self.residuals_compacted,
            self.bucket_weights,
            q,
            params.nprobe,
            params.num_tokens,
            params.mse_estimates,
            params.k,
        )
        return pids.tolist(), scores.tolist()
