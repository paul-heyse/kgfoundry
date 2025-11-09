"""Search interface for ColBERT and WARP indices.

This module provides the Searcher class for performing dense retrieval over
ColBERT/WARP indices. Supports single query search, batch search, and various
filtering and configuration options.
"""

from __future__ import annotations

import pathlib
from collections.abc import Callable
from typing import Any, Union

import torch
from tqdm import tqdm
from warp.data import Collection, Queries, Ranking
from warp.engine.config import WARPRunConfig
from warp.engine.search.index_storage import IndexScorerWARP
from warp.engine.search.parallel.parallel_index_storage import ParallelIndexScorerWARP
from warp.infra.config import ColBERTConfig
from warp.infra.launcher import print_memory_stats
from warp.infra.provenance import Provenance
from warp.infra.run import Run
from warp.modeling.checkpoint import Checkpoint
from warp.search.index_storage import IndexScorer
from warp.utils.tracker import NOPTracker, Tracker

# Batch size and search thresholds
DEFAULT_BATCH_SIZE = 128
SMALL_K_THRESHOLD = 10
MEDIUM_K_THRESHOLD = 100

TextQueries = Union[str, list[str], dict[int, str], Queries]


class Searcher:
    """Search interface for ColBERT and WARP indices.

    Provides methods for encoding queries, performing dense retrieval, and
    managing search configuration. Supports both standard ColBERT and WARP
    compressed indices with parallel execution options.

    Parameters
    ----------
    index : str
        Index name or path to load.
    checkpoint : str | None
        Path to checkpoint file (defaults to index checkpoint if not provided).
    collection : str | Collection | None
        Document collection (defaults to config collection if not provided).
    config : ColBERTConfig | WARPRunConfig | None
        Configuration object (merged with Run context).
    index_root : str | None
        Root directory for indices (defaults to config index_root).
    verbose : int
        Verbosity level (default: 3).
    warp_engine : bool
        Whether to use WARP compression engine (default: False).

    Attributes
    ----------
    index : str
        Full path to the index directory.
    config : ColBERTConfig
        Merged configuration for search.
    checkpoint : Checkpoint
        Loaded checkpoint for query encoding.
    ranker : IndexScorer | IndexScorerWARP | ParallelIndexScorerWARP
        Ranker instance for dense search.
    collection : Collection
        Document collection.
    warp_engine : bool
        Whether WARP engine is enabled.
    verbose : int
        Verbosity level.
    """

    def __init__(
        self,
        index: str,
        checkpoint: str | None = None,
        collection: str | Collection | None = None,
        config: ColBERTConfig | WARPRunConfig | None = None,
        index_root: str | None = None,
        verbose: int = 3,
        *,
        warp_engine: bool = False,
    ) -> None:
        self.verbose = verbose
        if self.verbose > 1:
            print_memory_stats()

        warp_config = None
        if isinstance(config, WARPRunConfig):
            warp_config = config
            config = warp_config.colbert()

        initial_config = ColBERTConfig.from_existing(config, Run().config)

        default_index_root = initial_config.index_root_
        index_root = index_root if index_root else default_index_root
        self.index = str(pathlib.Path(index_root) / index)
        self.index_config = ColBERTConfig.load_from_index(self.index)

        self.checkpoint = checkpoint or self.index_config.checkpoint
        self.checkpoint_config = ColBERTConfig.load_from_checkpoint(self.checkpoint)
        self.config = ColBERTConfig.from_existing(
            self.checkpoint_config, self.index_config, initial_config
        )

        self.collection = Collection.cast(collection or self.config.collection)
        self.configure(checkpoint=self.checkpoint, collection=self.collection)

        self.checkpoint = Checkpoint(
            self.checkpoint,
            colbert_config=self.config,
            verbose=self.verbose,
            warp_config=warp_config,
        )
        use_gpu = self.config.total_visible_gpus > 0
        if use_gpu:
            self.checkpoint = self.checkpoint.cuda()
        load_index_with_mmap = self.config.load_index_with_mmap
        if load_index_with_mmap and use_gpu:
            msg = "Memory-mapped index can only be used with CPU!"
            raise ValueError(msg)

        self.warp_engine = warp_engine
        if warp_engine:
            if torch.get_num_threads() == 1:
                self.ranker = IndexScorerWARP(
                    self.index,
                    self.config,
                    t_prime=warp_config.t_prime,
                    bound=warp_config.bound,
                    use_gpu=use_gpu,
                    load_index_with_mmap=load_index_with_mmap,
                )
            else:
                self.ranker = ParallelIndexScorerWARP(
                    self.index,
                    self.config,
                    t_prime=warp_config.t_prime,
                    bound=warp_config.bound,
                    use_gpu=use_gpu,
                    load_index_with_mmap=load_index_with_mmap,
                    fused_decompression_merge=warp_config.fused_ext,
                )
        else:
            self.ranker = IndexScorer(self.index, use_gpu, load_index_with_mmap)

        print_memory_stats()

    def configure(self, **kw_args: Any) -> None:  # noqa: ANN401
        """Update search configuration parameters.

        Parameters
        ----------
        **kw_args : Any
            Configuration parameters to update.
        """
        self.config.configure(**kw_args)

    def encode(self, text: TextQueries, *, full_length_search: bool = False) -> torch.Tensor:
        """Encode text queries into dense embeddings.

        Parameters
        ----------
        text : TextQueries
            Query text(s) - can be string, list of strings, dict, or Queries object.
        full_length_search : bool
            Whether to use full query length (default: False).

        Returns
        -------
        torch.Tensor
            Encoded query embeddings tensor.
        """
        queries = text if type(text) is list else [text]
        bsize = DEFAULT_BATCH_SIZE if len(queries) > DEFAULT_BATCH_SIZE else None

        self.checkpoint.query_tokenizer.query_maxlen = self.config.query_maxlen
        return self.checkpoint.query_from_text(
            queries, bsize=bsize, to_cpu=True, full_length_search=full_length_search
        )

    def search(
        self,
        text: str,
        k: int = 10,
        filter_fn: Callable[[int], bool] | None = None,
        pids: list[int] | None = None,
        tracker: Tracker = NOPTracker(),
        *,
        full_length_search: bool = False,
    ) -> tuple[list[int], list[int], list[float]]:
        """Search for top-k documents matching a single query.

        Parameters
        ----------
        text : str
            Query text string.
        k : int
            Number of results to return (default: 10).
        filter_fn : Callable[[int], bool] | None
            Optional filter function for passage IDs.
        full_length_search : bool
            Whether to use full query length (default: False).
        pids : list[int] | None
            Optional list of passage IDs to restrict search to.
        tracker : Tracker
            Execution tracker for timing (default: NOPTracker).

        Returns
        -------
        tuple[list[int], list[int], list[float]]
            Tuple of (passage_ids, ranks, scores) for top-k results.
        """
        tracker.begin("Query Encoding")
        q = self.encode(text, full_length_search=full_length_search)
        tracker.end("Query Encoding")
        return self.dense_search(q, k, filter_fn=filter_fn, pids=pids, tracker=tracker)

    def search_all(
        self,
        queries: TextQueries,
        k: int = 10,
        filter_fn: Callable[[int], bool] | None = None,
        qid_to_pids: dict[str, list[int]] | None = None,
        *,
        full_length_search: bool = False,
        show_progress: bool = True,
    ) -> Ranking:
        """Search for top-k documents matching multiple queries.

        Parameters
        ----------
        queries : TextQueries
            Queries to search - can be string, list, dict, or Queries object.
        k : int
            Number of results per query (default: 10).
        filter_fn : Callable[[int], bool] | None
            Optional filter function for passage IDs.
        full_length_search : bool
            Whether to use full query length (default: False).
        qid_to_pids : dict[str, list[int]] | None
            Optional mapping from query IDs to allowed passage ID lists.
        show_progress : bool
            Whether to show progress bar (default: True).

        Returns
        -------
        Ranking
            Ranking object containing results for all queries with provenance.
        """
        queries = Queries.cast(queries)
        queries_ = list(queries.values())

        q = self.encode(queries_, full_length_search=full_length_search)

        return self._search_all_q(
            queries,
            q,
            k,
            filter_fn=filter_fn,
            qid_to_pids=qid_to_pids,
            show_progress=show_progress,
        )

    def _search_all_q(
        self,
        queries: Queries,
        q: torch.Tensor,
        k: int,
        filter_fn: Callable[[int], bool] | None = None,
        qid_to_pids: dict[str, list[int]] | None = None,
        *,
        show_progress: bool = True,
    ) -> Ranking:
        qids = list(queries.keys())

        if qid_to_pids is None:
            qid_to_pids = dict.fromkeys(qids)

        all_scored_pids = [
            list(
                zip(
                    *self.dense_search(
                        q[query_idx : query_idx + 1],
                        k,
                        filter_fn=filter_fn,
                        pids=qid_to_pids[qid],
                    ),
                    strict=False,
                )
            )
            for query_idx, qid in tqdm(enumerate(qids), disable=not show_progress)
        ]

        data = dict(zip(queries.keys(), all_scored_pids, strict=False))

        provenance = Provenance()
        provenance.source = "Searcher::search_all"
        provenance.queries = queries.provenance()
        provenance.config = self.config.export()
        provenance.k = k

        return Ranking(data=data, provenance=provenance)

    def dense_search(
        self,
        q: torch.Tensor,
        k: int = 10,
        filter_fn: Callable[[int], bool] | None = None,
        pids: list[int] | None = None,
        tracker: Tracker = NOPTracker(),
    ) -> tuple[list[int], list[int], list[float]]:
        """Perform dense search using pre-encoded query embeddings.

        Automatically configures search parameters (ncells, centroid_score_threshold,
        ndocs) based on k value for optimal performance.

        Parameters
        ----------
        q : torch.Tensor
            Pre-encoded query embeddings tensor.
        k : int
            Number of results to return (default: 10).
        filter_fn : Callable[[int], bool] | None
            Optional filter function for passage IDs.
        pids : list[int] | None
            Optional list of passage IDs to restrict search to.
        tracker : Tracker
            Execution tracker for timing (default: NOPTracker).

        Returns
        -------
        tuple[list[int], list[int], list[float]]
            Tuple of (passage_ids, ranks, scores) for top-k results.
        """
        if k <= SMALL_K_THRESHOLD:
            if self.config.ncells is None:
                self.configure(ncells=1)
            if self.config.centroid_score_threshold is None:
                self.configure(centroid_score_threshold=0.5)
            if self.config.ndocs is None:
                self.configure(ndocs=256)
        elif k <= MEDIUM_K_THRESHOLD:
            if self.config.ncells is None:
                self.configure(ncells=2)
            if self.config.centroid_score_threshold is None:
                self.configure(centroid_score_threshold=0.45)
            if self.config.ndocs is None:
                self.configure(ndocs=1024)
        else:
            if self.config.ncells is None:
                self.configure(ncells=4)
            if self.config.centroid_score_threshold is None:
                self.configure(centroid_score_threshold=0.4)
            if self.config.ndocs is None:
                self.configure(ndocs=max(k * 4, 4096))

        if self.warp_engine:
            pids, scores = self.ranker.rank(
                self.config, q, k=k, filter_fn=filter_fn, pids=pids, tracker=tracker
            )
        else:
            pids, scores = self.ranker.rank(
                self.config, q, filter_fn=filter_fn, pids=pids, tracker=tracker
            )

        return pids[:k], list(range(1, k + 1)), scores[:k]
