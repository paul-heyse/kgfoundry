"""WARP-specific index loading and scoring.

This module provides IndexLoaderWARP and IndexScorerWARP for loading
and scoring with WARP-specific index formats.
"""

from __future__ import annotations

import os
import pathlib

import numpy as np
import torch
from torch.utils.cpp_extension import load
from warp.engine.constants import T_PRIME_MAX, TPrimePolicy
from warp.infra.config.config import ColBERTConfig
from warp.utils.tracker import DEFAULT_NOP_TRACKER, NOPTracker
from warp.utils.utils import print_message


class IndexLoaderWARP:
    """WARP-specific index loader.

    Loads WARP-compacted index format with bucket weights, centroids,
    codes, and residuals. CPU-only (use_gpu must be False).

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
    ) -> None:
        if use_gpu:
            msg = "use_gpu must be False for IndexLoaderWARP"
            raise ValueError(msg)
        if load_index_with_mmap:
            msg = "load_index_with_mmap must be False for IndexLoaderWARP"
            raise ValueError(msg)

        self.index_path = index_path
        self.use_gpu = use_gpu
        self.load_index_with_mmap = load_index_with_mmap

        print_message("#> Loading buckets...")
        index_path_obj = pathlib.Path(self.index_path)
        bucket_weights = torch.from_numpy(np.load(index_path_obj / "bucket_weights.npy"))
        self.bucket_weights = bucket_weights

        self._load_codec()
        print_message("#> Loading repacked residuals...")
        self.residuals_compacted = torch.load(index_path_obj / "residuals.repacked.compacted.pt")

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


class IndexScorerWARP(IndexLoaderWARP):
    """WARP-specific index scorer.

    Extends IndexLoaderWARP with scoring capabilities using WARP-specific
    compression and candidate selection. CPU-only (use_gpu must be False).

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

    Raises
    ------
    ValueError
        If use_gpu=True, load_index_with_mmap=True, config.ncells is None,
        or config.nbits not in {2, 4}.
    """

    def __init__(
        self,
        index_path: str,
        config: ColBERTConfig,
        t_prime: int | None = None,
        bound: int = 128,
        *,
        use_gpu: bool = False,
        load_index_with_mmap: bool = False,
    ) -> None:
        if use_gpu:
            msg = "use_gpu must be False for IndexScorerWARP"
            raise ValueError(msg)
        if load_index_with_mmap:
            msg = "load_index_with_mmap must be False for IndexScorerWARP"
            raise ValueError(msg)

        super().__init__(
            index_path=index_path,
            config=config,
            use_gpu=use_gpu,
            load_index_with_mmap=load_index_with_mmap,
        )

        IndexScorerWARP.try_load_torch_extensions(use_gpu=use_gpu)

        if config.ncells is None:
            msg = "config.ncells must be set"
            raise ValueError(msg)
        self.nprobe = config.ncells

        (num_centroids, _) = self.centroids.shape
        if t_prime is not None:
            self.t_prime = TPrimePolicy(value=t_prime)
        elif num_centroids <= 2**16:
            (num_embeddings, _) = self.residuals_compacted.shape
            self.t_prime = TPrimePolicy(value=int(np.sqrt(8 * num_embeddings) / 1000) * 1000)
        else:
            self.t_prime = T_PRIME_MAX

        if config.nbits not in {2, 4}:
            msg = f"config.nbits must be 2 or 4, got {config.nbits}"
            raise ValueError(msg)
        self.nbits = config.nbits

        self.bound = bound or 128

    @classmethod
    def try_load_torch_extensions(cls, *, use_gpu: bool) -> None:
        """Load CUDA extensions for WARP scoring.

        Loads warp_select_centroids_cpp, decompress_centroids_cpp, and
        merge_candidate_scores_cpp extensions if GPU is available and
        extensions haven't been loaded yet.

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
            "Loading warp_select_centroids_cpp extension "
            "(set WARP_LOAD_TORCH_EXTENSION_VERBOSE=True for more info)..."
        )
        cls.warp_select_centroids_cpp = load(
            name="warp_select_centroids_cpp",
            sources=[
                str(pathlib.Path(__file__).parent.resolve() / "warp_select_centroids.cpp"),
            ],
            extra_cflags=cflags,
            verbose=os.getenv("WARP_LOAD_TORCH_EXTENSION_VERBOSE", "False") == "True",
        ).warp_select_centroids_cpp

        print_message(
            "Loading decompress_centroids_cpp extension "
            "(set WARP_LOAD_TORCH_EXTENSION_VERBOSE=True for more info)..."
        )
        cls.decompress_centroids_cpp = {}
        decompress_centroids_cpp = load(
            name="decompress_centroids_cpp",
            sources=[
                str(pathlib.Path(__file__).parent.resolve() / "decompress_centroids.cpp"),
            ],
            extra_cflags=cflags,
            verbose=os.getenv("WARP_LOAD_TORCH_EXTENSION_VERBOSE", "False") == "True",
        )
        cls.decompress_centroids_cpp[2] = decompress_centroids_cpp.decompress_centroids_2_cpp
        cls.decompress_centroids_cpp[4] = decompress_centroids_cpp.decompress_centroids_4_cpp

        print_message(
            "Loading merge_candidate_scores_cpp extension "
            "(set WARP_LOAD_TORCH_EXTENSION_VERBOSE=True for more info)..."
        )
        cls.merge_candidate_scores_cpp = load(
            name="merge_candidate_scores_cpp",
            sources=[
                str(pathlib.Path(__file__).parent.resolve() / "merge_candidate_scores.cpp"),
            ],
            extra_cflags=cflags,
            verbose=os.getenv("WARP_LOAD_TORCH_EXTENSION_VERBOSE", "False") == "True",
        ).merge_candidate_scores_cpp

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
        """Rank passages for queries using WARP scoring.

        Generates candidates, decompresses centroids, merges scores, and
        returns top-k results.

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

            tracker.begin("Decompression")
            capacities, candidate_sizes, candidate_pids, candidate_scores = (
                self._decompress_centroids(q.squeeze(0), cells, centroid_scores, self.nprobe)
            )
            tracker.end("Decompression")

            tracker.begin("Build Matrix")
            pids, scores = self._merge_candidate_scores(
                capacities,
                candidate_sizes,
                candidate_pids,
                candidate_scores,
                mse_estimates,
                k,
            )
            tracker.end("Build Matrix")

            return pids, scores

    def _warp_select_centroids(
        self,
        q_mask: torch.Tensor,
        centroid_scores: torch.Tensor,
        nprobe: int,
        t_prime: int,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        cells, scores, mse = IndexScorerWARP.warp_select_centroids_cpp(
            q_mask, centroid_scores, self.sizes_compacted, nprobe, t_prime, self.bound
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
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        centroid_ids = centroid_ids.long()
        begins = self.offsets_compacted[centroid_ids]
        ends = self.offsets_compacted[centroid_ids + 1]

        capacities = ends - begins
        sizes, pids, scores = IndexScorerWARP.decompress_centroids_cpp[self.nbits](
            begins,
            ends,
            capacities,
            centroid_scores,
            self.codes_compacted,
            self.residuals_compacted,
            self.bucket_weights,
            q,
            nprobe,
        )
        return capacities, sizes, pids, scores

    def _merge_candidate_scores(
        self,
        capacities: torch.Tensor,
        candidate_sizes: torch.Tensor,
        candidate_pids: torch.Tensor,
        candidate_scores: torch.Tensor,
        mse_estimates: torch.Tensor,
        k: int,
    ) -> tuple[list[int], list[float]]:
        pids, scores = IndexScorerWARP.merge_candidate_scores_cpp(
            capacities,
            candidate_sizes,
            candidate_pids,
            candidate_scores,
            mse_estimates,
            self.nprobe,
            k,
        )
        return pids.tolist(), scores.tolist()
