"""WARP-specific searcher wrapper with collection mapping support.

This module provides WARPSearcher, a wrapper around the base Searcher that
handles WARP-specific configuration, collection mapping for re-indexed
collections, and batched/unbatched search modes.
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Iterable

from tqdm import tqdm
from warp import Searcher
from warp.data.queries import WARPQueries
from warp.data.ranking import WARPRanking, WARPRankingItem, WARPRankingItems
from warp.engine.config import WARPRunConfig
from warp.infra import Run, RunConfig
from warp.utils.tracker import NOPTracker


class WARPSearcher:
    """WARP-specific searcher with collection mapping and batched search.

    Wraps the base Searcher with WARP configuration and provides automatic
    collection mapping for re-indexed collections. Supports both batched
    and unbatched search modes.

    Parameters
    ----------
    config : WARPRunConfig
        WARP run configuration specifying index, collection, and search parameters.

    Attributes
    ----------
    config : WARPRunConfig
        WARP configuration.
    searcher : Searcher
        Underlying ColBERT/WARP searcher instance.
    collection_map : dict[int, int] | None
        Optional mapping from old to new passage IDs (if collection_map.json exists).
    """

    def __init__(self, config: WARPRunConfig) -> None:
        self.config = config
        with Run().context(RunConfig(nranks=config.nranks, experiment=config.experiment_name)):
            self.searcher = Searcher(
                index=config.index_name,
                config=config,
                index_root=config.index_root,
                warp_engine=True,
            )

        collection_map_path = pathlib.Path(config.collection_path).parent / "collection_map.json"
        if pathlib.Path(collection_map_path).exists():
            with pathlib.Path(collection_map_path).open(encoding="utf-8") as file:
                collection_map = json.load(file)
                collection_map = {int(key): value for key, value in collection_map.items()}
            self.collection_map = collection_map
        else:
            self.collection_map = None

    def search_all(
        self,
        queries: WARPQueries | Iterable[tuple[str, str]],
        k: int | None = None,
        tracker: NOPTracker = NOPTracker(),
        *,
        batched: bool = True,
        show_progress: bool = True,
    ) -> WARPRanking:
        """Search for multiple queries with batched or unbatched execution.

        Parameters
        ----------
        queries
            Queries to search (WARPQueries or iterable of (qid, query) pairs).
        k : int | None
            Top-k value (defaults to config.k if None).
        batched : bool
            Whether to use batched search (default: True). Automatically disabled
            if ONNX runtime is configured.
        tracker : Tracker
            Execution tracker for timing (default: NOPTracker).
        show_progress : bool
            Whether to show progress bar (default: True).

        Returns
        -------
        WARPRanking
            Ranking results for all queries.
        """
        if batched and self.config.onnx is not None:
            batched = False
        if batched:
            return self._search_all_batched(queries, k, tracker, show_progress=show_progress)
        return self._search_all_unbatched(queries, k, tracker, show_progress=show_progress)

    def _search_all_batched(
        self,
        queries: WARPQueries | Iterable[tuple[str, str]],
        k: int | None = None,
        tracker: NOPTracker = NOPTracker(),
        *,
        show_progress: bool = True,
    ) -> WARPRanking:
        if k is None:
            k = self.config.k
        if isinstance(queries, WARPQueries):
            queries = queries.queries
        ranking = self.searcher.search_all(
            queries, k=k, tracker=tracker, show_progress=show_progress
        )
        if self.collection_map is not None:
            ranking.apply_collection_map(self.collection_map)
        return WARPRanking(ranking)

    def _search_all_unbatched(
        self,
        queries: WARPQueries | Iterable[tuple[str, str]],
        k: int | None = None,
        tracker: NOPTracker = NOPTracker(),
        *,
        show_progress: bool = True,
    ) -> WARPRanking:
        if k is None:
            k = self.config.k
        results = WARPRankingItems()
        for qid, qtext in tqdm(queries, disable=not show_progress):
            tracker.next_iteration()
            results += WARPRankingItem(qid=qid, results=self.search(qtext, k=k, tracker=tracker))
            tracker.end_iteration()
        return results.finalize(self, queries.provenance(source="Searcher::search", k=k))

    def search(
        self,
        query: str,
        k: int | None = None,
        tracker: NOPTracker = NOPTracker(),
    ) -> tuple[list[int], list[int], list[float]]:
        """Search for a single query.

        Parameters
        ----------
        query
            Query text string.
        k : int | None
            Top-k value (defaults to config.k if None).
        tracker : Tracker
            Execution tracker for timing (default: NOPTracker).

        Returns
        -------
        tuple[list[int], list[int], list[float]]
            Tuple of (passage_ids, ranks, scores) for top-k results.
        """
        if k is None:
            k = self.config.k
        return self.searcher.search(query, k=k, tracker=tracker)
