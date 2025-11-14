"""Exact reranking utilities for FAISS candidates."""

from __future__ import annotations

from time import perf_counter

import numpy as np

from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from codeintel_rev.observability.semantic_conventions import Attrs
from codeintel_rev.telemetry.decorators import span_context
from codeintel_rev.telemetry.otel_metrics import build_histogram
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)
_VECTOR_AXIS = 2
_CANDIDATE_MATRIX_NDIM = 2
_SIMILARITY_EPS = 1e-9

RERANK_LATENCY_MS = build_histogram(
    "codeintel_rerank_exact_latency_ms",
    "Latency of the exact rerank stage.",
    unit="ms",
)


def _perform_exact_rerank(
    catalog: DuckDBCatalog,
    queries: np.ndarray,
    candidate_ids: np.ndarray,
    *,
    top_k: int,
    metric: str = "ip",
) -> tuple[np.ndarray, np.ndarray]:
    """Hydrate embeddings for candidate ids and compute exact similarities.

    This function performs exact reranking of approximate nearest neighbor (ANN)
    search candidates by retrieving the original embeddings from the catalog and
    computing exact similarity scores (inner product or cosine similarity). The
    candidates are then sorted by exact similarity and the top-k results are
    returned. This improves recall compared to using approximate distances from
    the FAISS index.

    The function handles missing embeddings gracefully by returning sentinel values
    (minimum float32 for scores, -1 for IDs) when embeddings are not found in the
    catalog. Invalid candidate IDs (negative values) are filtered out before
    similarity computation.

    Parameters
    ----------
    catalog : DuckDBCatalog
        Catalog instance providing get_embeddings_by_ids() method for batch
        embedding retrieval. The catalog must contain embeddings for the candidate
        chunk IDs.
    queries : np.ndarray
        Query vectors shaped `(B, dim)` or `(dim,)` where B is the batch size and
        dim is the embedding dimension. Automatically reshaped to 2D if 1D.
        Dtype should be float32 or convertible to float32.
    candidate_ids : np.ndarray
        Candidate chunk identifiers shaped `(B, K')` where B matches the query
        batch size and K' is the number of candidates per query (typically larger
        than top_k). Dtype should be int64 or convertible to int64. Negative IDs
        are treated as invalid and filtered out.
    top_k : int
        Number of top results to return per query after reranking. Must be positive.
        The function returns the top-k candidates sorted by exact similarity score
        (descending order).
    metric : str, optional
        Similarity metric to use for exact computation. ``"ip"`` (inner product)
        by default, which computes dot product between query and candidate vectors.
        ``"cos"`` (cosine similarity) normalizes both queries and candidates to
        unit length before computing inner product. Defaults to ``"ip"``.

    Returns
    -------
    np.ndarray
        Scores array with shape `(B, top_k)`, dtype float32. Exact similarity
        scores (inner product or cosine similarity) for the top-k reranked candidates.
        Scores are sorted in descending order (highest similarity first). Missing
        or invalid candidates are filled with minimum float32 value.
    np.ndarray
        IDs array with shape `(B, top_k)`, dtype int64. Chunk identifiers
        corresponding to the top-k reranked candidates. Missing or invalid
        candidates are filled with -1.

    Raises
    ------
    ValueError
        Raised in the following cases:
        - ``top_k <= 0``: top_k must be positive for rerank operations
        - ``candidate_ids`` shape mismatch: candidate_ids must be shaped (B, K')
          and aligned with query batch size B
        - Embedding dimension mismatch: retrieved embeddings have different
          dimension than query vectors
        - Effective top_k <= 0: occurs when k_prime (number of candidates) is
          zero or negative after filtering

    Notes
    -----
    This function performs exact similarity computation which is more accurate
    than approximate distances but slower. Time complexity: O(B * K' * dim) for
    similarity computation plus O(B * K' * log(K')) for sorting. The function
    handles missing embeddings gracefully by returning sentinel values rather
    than raising exceptions. When no embeddings are found for any candidate IDs,
    the function returns arrays filled with sentinel values (minimum scores, -1 IDs)
    with shape (B, min(top_k, K')). Thread-safe if the catalog instance is
    thread-safe. The function uses einsum for efficient batch similarity computation
    and argpartition for efficient top-k selection.
    """
    if top_k <= 0:
        msg = "top_k must be positive for rerank operations"
        raise ValueError(msg)

    start = perf_counter()
    query_mat = _normalize_queries(queries)
    candidates = _prepare_candidate_matrix(candidate_ids, query_mat.shape[0])
    candidate_total = int(np.size(candidates))
    if not np.any(candidates >= 0):
        return _empty_result(query_mat.shape[0], min(top_k, candidates.shape[1]))

    span_attrs = {
        Attrs.REQUEST_STAGE: "rerank",
        Attrs.RETRIEVAL_TOP_K: top_k,
        "candidates": candidate_total,
        "metric": metric,
    }
    with span_context(
        "retrieval.rerank_exact",
        stage="rerank.exact",
        attrs=span_attrs,
        emit_checkpoint=True,
    ):
        lookup, embedding_dim = _hydrate_embeddings(catalog, candidates)
        if not lookup:
            LOGGER.warning(
                "Exact rerank skipped: no embeddings returned for %s ids",
                np.unique(candidates[candidates >= 0]).size,
            )
            return _empty_result(query_mat.shape[0], min(top_k, candidates.shape[1]))
        if embedding_dim != query_mat.shape[1]:
            msg = f"Embedding dimension mismatch: {embedding_dim} != {query_mat.shape[1]}"
            raise ValueError(msg)

        vectors, filled = _build_candidate_vectors(candidates, lookup, embedding_dim)
        similarities = _compute_similarity(query_mat, vectors, filled, metric)
        k_eff = _effective_top_k(top_k, candidates.shape[1])
        scores, ids = _select_topk(candidates, similarities, k_eff)
    duration_ms = (perf_counter() - start) * 1000.0
    RERANK_LATENCY_MS.observe(duration_ms)
    return scores, ids


def _normalize_queries(queries: np.ndarray) -> np.ndarray:
    """Normalize query vectors to 2D array format for batch processing.

    This helper function ensures query vectors are in the correct shape for
    batch similarity computation. Single query vectors (1D) are reshaped to
    2D with batch size 1, while batch queries (2D) are passed through unchanged.
    The function also ensures float32 dtype for consistent computation.

    Parameters
    ----------
    queries : np.ndarray
        Query vectors of shape `(B, dim)` or `(dim,)` where B is the batch size
        and dim is the embedding dimension. Dtype is converted to float32 if needed.

    Returns
    -------
    np.ndarray
        Normalized query matrix with shape `(B, dim)` where B >= 1. Single queries
        are reshaped to `(1, dim)`. Dtype is float32. The array is ready for
        batch similarity computation with candidate vectors.

    Notes
    -----
    This function is part of the exact reranking pipeline and ensures consistent
    input format for downstream processing. Time complexity: O(B * dim) for dtype
    conversion and reshaping. The function performs no I/O operations and is
    thread-safe.
    """
    query_mat = np.asarray(queries, dtype=np.float32)
    if query_mat.ndim == 1:
        query_mat = query_mat.reshape(1, -1)
    return query_mat


def _prepare_candidate_matrix(candidate_ids: np.ndarray, batch_size: int) -> np.ndarray:
    """Validate and prepare candidate ID matrix for embedding retrieval.

    This helper function validates that candidate IDs are in the correct 2D format
    and aligned with the query batch size. It ensures dtype is int64 for consistent
    ID handling and raises ValueError if the shape is invalid. This validation
    prevents downstream errors during embedding lookup and similarity computation.

    Parameters
    ----------
    candidate_ids : np.ndarray
        Candidate chunk identifiers of any shape. Will be converted to int64 dtype
        and validated to ensure 2D shape `(batch_size, K')` where batch_size matches
        the query batch size.
    batch_size : int
        Expected batch size (number of queries). The first dimension of candidate_ids
        must match this value. Used to validate alignment between queries and candidates.

    Returns
    -------
    np.ndarray
        Validated candidate ID matrix with shape `(batch_size, K')` and dtype int64.
        The matrix is ready for embedding retrieval and similarity computation.

    Raises
    ------
    ValueError
        Raised when candidate_ids is not 2D or when the batch dimension doesn't
        match the expected batch_size. This ensures queries and candidates are
        properly aligned for batch processing.

    Notes
    -----
    This function is part of the exact reranking pipeline and performs input
    validation before expensive embedding retrieval operations. Time complexity:
    O(1) for shape validation plus O(n) for dtype conversion where n is the
    number of candidate IDs. The function performs no I/O operations and is
    thread-safe.
    """
    candidates = np.asarray(candidate_ids, dtype=np.int64)
    if candidates.ndim != _CANDIDATE_MATRIX_NDIM or candidates.shape[0] != batch_size:
        msg = "candidate_ids must be shaped (batch, K') and aligned with query batch size"
        raise ValueError(msg)
    return candidates


def _hydrate_embeddings(
    catalog: DuckDBCatalog, candidates: np.ndarray
) -> tuple[dict[int, np.ndarray], int]:
    """Retrieve embeddings from catalog for valid candidate IDs.

    This helper function performs batch embedding retrieval from the DuckDB catalog
    for all valid (non-negative) candidate chunk IDs. It filters out invalid IDs,
    deduplicates IDs to minimize catalog queries, and builds a lookup dictionary
    mapping chunk IDs to their embedding vectors. This lookup enables efficient
    vector assembly during candidate vector construction.

    Parameters
    ----------
    catalog : DuckDBCatalog
        DuckDB catalog instance providing get_embeddings_by_ids() method for batch
        embedding retrieval. The catalog must contain embeddings for the candidate
        chunk IDs. Missing embeddings are handled gracefully (empty lookup returned).
    candidates : np.ndarray
        Candidate chunk ID matrix with shape `(batch, K')` and dtype int64. Invalid
        IDs (negative values) are automatically filtered out before catalog query.
        The function extracts unique IDs to minimize redundant catalog lookups.

    Returns
    -------
    dict[int, np.ndarray]
        Lookup dictionary mapping chunk IDs to their embedding vectors. Keys are
        integer chunk IDs; values are float32 numpy arrays with shape `(dim,)`
        where dim is the embedding dimension. Empty dictionary when no valid IDs
        exist or no embeddings are found in the catalog.
    int
        Embedding dimension (number of features per vector). Returns 0 when no
        embeddings are retrieved. Used to validate dimension consistency with
        query vectors and allocate candidate vector arrays.

    Notes
    -----
    This function is part of the exact reranking pipeline and performs the critical
    step of retrieving original embeddings for exact similarity computation. Time
    complexity: O(n) for filtering and deduplication plus O(m) for catalog query
    where n is the number of candidate IDs and m is the number of unique IDs. The
    function performs database I/O via the catalog and is thread-safe if the catalog
    instance is thread-safe. Missing embeddings are handled gracefully - the function
    returns an empty lookup rather than raising exceptions, allowing the caller to
    handle missing data appropriately.
    """
    valid_ids = candidates[candidates >= 0]
    if valid_ids.size == 0:
        return {}, 0
    unique_ids = np.unique(valid_ids)
    id_list, emb_matrix = catalog.get_embeddings_by_ids(unique_ids.tolist())
    if not id_list:
        return {}, 0
    lookup = {int(chunk_id): vec for chunk_id, vec in zip(id_list, emb_matrix, strict=True)}
    return lookup, emb_matrix.shape[1]


def _build_candidate_vectors(
    candidates: np.ndarray,
    embedding_lookup: dict[int, np.ndarray],
    dim: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Assemble candidate embedding vectors from lookup dictionary.

    This helper function constructs a 3D array of candidate embedding vectors
    by mapping chunk IDs from the candidate matrix to their corresponding
    embeddings in the lookup dictionary. It maintains the batch and candidate
    structure while filling in embedding vectors. A boolean mask tracks which
    positions have valid embeddings, enabling downstream similarity computation
    to handle missing embeddings gracefully.

    Parameters
    ----------
    candidates : np.ndarray
        Candidate chunk ID matrix with shape `(batch, width)` and dtype int64.
        Each element is a chunk ID that maps to an embedding in the lookup
        dictionary. Negative IDs are skipped (treated as invalid).
    embedding_lookup : dict[int, np.ndarray]
        Dictionary mapping chunk IDs to their embedding vectors. Keys are integer
        chunk IDs; values are float32 numpy arrays with shape `(dim,)`. Missing
        IDs result in zero-filled vectors with corresponding filled mask set to False.
    dim : int
        Embedding dimension (number of features per vector). Used to allocate
        the candidate vector array with shape `(batch, width, dim)`. Must match
        the dimension of vectors in embedding_lookup.

    Returns
    -------
    np.ndarray
        Candidate embedding vectors with shape `(batch, width, dim)` and dtype
        float32. Each position `[b, k, :]` contains the embedding vector for
        candidate ID `candidates[b, k]` if available, otherwise zeros. The vectors
        are ready for batch similarity computation with query vectors.
    np.ndarray
        Boolean mask with shape `(batch, width)` indicating which positions have
        valid embeddings. True indicates the embedding was found in the lookup
        dictionary; False indicates missing or invalid embedding (zero-filled).
        Used to mask invalid similarities during computation.

    Notes
    -----
    This function is part of the exact reranking pipeline and performs the vector
    assembly step before similarity computation. Time complexity: O(batch * width)
    for iterating through candidate IDs and dictionary lookups. The function
    performs no I/O operations and is thread-safe. Missing embeddings result in
    zero-filled vectors rather than raising exceptions, allowing graceful handling
    of incomplete data during reranking.
    """
    batch, width = candidates.shape
    vectors = np.zeros((batch, width, dim), dtype=np.float32)
    filled = np.zeros_like(candidates, dtype=bool)
    total = width
    flat = candidates.flatten()
    for index, chunk_id in enumerate(flat):
        if chunk_id < 0:
            continue
        vector = embedding_lookup.get(int(chunk_id))
        if vector is None:
            continue
        row = index // total
        col = index % total
        vectors[row, col, :] = vector
        filled[row, col] = True
    return vectors, filled


def _compute_similarity(
    query_mat: np.ndarray,
    vectors: np.ndarray,
    filled: np.ndarray,
    metric: str,
) -> np.ndarray:
    """Compute batch similarity scores between queries and candidate vectors.

    This helper function computes exact similarity scores (inner product or cosine
    similarity) between query vectors and candidate embedding vectors. It supports
    two metrics: "ip" (inner product) for fast computation and "cos" (cosine
    similarity) for normalized similarity. The function uses einsum for efficient
    batch computation and masks invalid embeddings (missing vectors) with minimum
    float32 values to exclude them from top-k selection.

    Parameters
    ----------
    query_mat : np.ndarray
        Query vectors with shape `(batch, dim)` and dtype float32. Each row represents
        one query vector. The queries are broadcast to match candidate vector dimensions
        for batch similarity computation.
    vectors : np.ndarray
        Candidate embedding vectors with shape `(batch, width, dim)` and dtype float32.
        Each position `[b, k, :]` contains an embedding vector for candidate k in
        batch b. Missing embeddings are zero-filled (handled via filled mask).
    filled : np.ndarray
        Boolean mask with shape `(batch, width)` indicating valid embeddings. True
        indicates the embedding vector is valid; False indicates missing/invalid
        (zero-filled). Used to mask similarities for invalid candidates.
    metric : str
        Similarity metric to use: "ip" for inner product (dot product) or "cos" for
        cosine similarity (normalized inner product). Cosine similarity normalizes
        both queries and candidates to unit length before computation.

    Returns
    -------
    np.ndarray
        Similarity scores with shape `(batch, width)` and dtype float32. Each element
        `[b, k]` contains the similarity score between query `b` and candidate `k`.
        Scores are inner products (range depends on vector magnitudes) or cosine
        similarities (range [-1, 1] after normalization). Invalid candidates (filled[b, k]
        == False) have scores set to minimum float32 value to exclude them from top-k.

    Notes
    -----
    This function is part of the exact reranking pipeline and performs the core
    similarity computation step. Time complexity: O(batch * width * dim) for einsum
    computation plus O(batch * width * dim) for cosine normalization when metric="cos".
    The function uses einsum for efficient batch operations and broadcasting to avoid
    explicit loops. Invalid embeddings are masked rather than raising exceptions,
    allowing graceful handling of missing data. Thread-safe and performs no I/O
    operations. Cosine similarity uses epsilon (1e-9) to prevent division by zero.
    """
    query_expanded = np.broadcast_to(query_mat[:, None, :], vectors.shape)
    target_vectors = vectors
    if metric == "cos":
        query_norm = (
            np.linalg.norm(query_expanded, axis=_VECTOR_AXIS, keepdims=True) + _SIMILARITY_EPS
        )
        cand_norm = (
            np.linalg.norm(target_vectors, axis=_VECTOR_AXIS, keepdims=True) + _SIMILARITY_EPS
        )
        query_expanded /= query_norm
        target_vectors /= cand_norm
    sims = np.einsum("bid,bid->bi", target_vectors, query_expanded, optimize=True)
    sims[~filled] = np.finfo(np.float32).min
    return sims


def _effective_top_k(requested: int, available: int) -> int:
    """Compute effective top-k value bounded by available candidates.

    This helper function computes the effective number of results to return,
    ensuring it doesn't exceed the number of available candidates. It validates
    that the effective k is positive, preventing downstream errors during top-k
    selection. This is necessary because the number of candidates may be smaller
    than the requested top_k (e.g., when filtering invalid IDs or when few
    candidates exist).

    Parameters
    ----------
    requested : int
        Requested number of top results (top_k parameter). Must be positive.
        This is the desired number of results per query.
    available : int
        Number of available candidates (width of candidate matrix). This may be
        smaller than requested if candidates were filtered or if the candidate
        matrix is narrow. Must be non-negative.

    Returns
    -------
    int
        Effective top-k value, computed as min(requested, available). This is
        the actual number of results that can be returned, bounded by available
        candidates. Always positive (validated before return).

    Raises
    ------
    ValueError
        Raised when the effective top_k is zero or negative. This occurs when
        both requested and available are zero, or when available is negative
        (should not happen in normal operation). Prevents downstream errors in
        top-k selection operations.

    Notes
    -----
    This function is part of the exact reranking pipeline and performs bounds
    checking before expensive top-k selection operations. Time complexity: O(1)
    for min computation and validation. The function performs no I/O operations
    and is thread-safe. This validation ensures that argpartition and sorting
    operations receive valid k values.
    """
    k_eff = min(requested, available)
    if k_eff <= 0:
        msg = "Effective top_k must be positive"
        raise ValueError(msg)
    return k_eff


def _select_topk(
    candidates: np.ndarray,
    similarities: np.ndarray,
    top_k: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Select top-k candidates by similarity score with efficient partial sorting.

    This helper function performs efficient top-k selection using argpartition for
    O(n) partial sorting followed by full sorting of the top-k subset. It selects
    the k highest-scoring candidates per query, sorts them by score (descending),
    and returns both the sorted scores and corresponding candidate IDs. This two-phase
    approach (partition + sort) is more efficient than full sorting when k << n.

    Parameters
    ----------
    candidates : np.ndarray
        Candidate chunk ID matrix with shape `(batch, width)` and dtype int64.
        Each element is a chunk ID corresponding to a similarity score in the
        similarities array. Used to retrieve IDs for top-k selected candidates.
    similarities : np.ndarray
        Similarity scores with shape `(batch, width)` and dtype float32. Each element
        `[b, k]` contains the similarity score between query `b` and candidate `k`.
        Scores are used to select the top-k candidates per query (highest scores).
    top_k : int
        Number of top candidates to select per query. Must be positive and <= width.
        The function returns the top-k highest-scoring candidates sorted by score
        (descending order).

    Returns
    -------
    np.ndarray
        Top-k similarity scores with shape `(batch, top_k)` and dtype float32.
        Scores are sorted in descending order (highest similarity first) within each
        query. Each row contains the k highest scores for that query.
    np.ndarray
        Top-k candidate IDs with shape `(batch, top_k)` and dtype int64. IDs correspond
        to the top-k scores and are aligned with the scores array. Each row contains
        the k chunk IDs with highest similarity scores for that query.

    Notes
    -----
    This function is part of the exact reranking pipeline and performs the final
    selection step before returning results. Time complexity: O(batch * width) for
    argpartition plus O(batch * top_k * log(top_k)) for sorting the top-k subset.
    This is more efficient than full sorting O(batch * width * log(width)) when
    top_k << width. The function uses argpartition for efficient partial sorting
    and argsort for final ordering. Thread-safe and performs no I/O operations.
    The function ensures consistent dtype (float32 for scores, int64 for IDs) for
    downstream compatibility.
    """
    row_index = np.arange(candidates.shape[0])[:, None]
    topk_idx = np.argpartition(-similarities, kth=top_k - 1, axis=1)[:, :top_k]
    topk_scores = similarities[row_index, topk_idx]
    order = np.argsort(-topk_scores, axis=1)
    ordered_scores = topk_scores[row_index, order]
    ordered_ids = candidates[row_index, topk_idx[row_index, order]]
    return ordered_scores.astype(np.float32, copy=False), ordered_ids.astype(np.int64, copy=False)


def _empty_result(batch: int, width: int) -> tuple[np.ndarray, np.ndarray]:
    """Create sentinel result arrays for empty or failed reranking operations.

    This helper function creates placeholder result arrays filled with sentinel
    values when reranking cannot be performed (e.g., no valid candidates, no
    embeddings found). The sentinel values (minimum float32 for scores, -1 for
    IDs) clearly indicate missing results and allow downstream code to handle
    empty results gracefully without raising exceptions.

    Parameters
    ----------
    batch : int
        Batch size (number of queries). Used to create result arrays with the
        correct first dimension. Must be positive.
    width : int
        Width of result arrays (number of results per query). Typically set to
        min(top_k, available_candidates) to match expected output shape. Must be
        positive.

    Returns
    -------
    np.ndarray
        Sentinel scores array with shape `(batch, width)` and dtype float32.
        All values are set to minimum float32 (np.finfo(np.float32).min) to
        indicate missing/invalid results. This ensures these positions are excluded
        from any meaningful similarity comparisons.
    np.ndarray
        Sentinel IDs array with shape `(batch, width)` and dtype int64. All values
        are set to -1 to indicate missing/invalid chunk identifiers. This sentinel
        value is clearly distinguishable from valid chunk IDs (which are non-negative).

    Notes
    -----
    This function is part of the exact reranking pipeline and provides graceful
    fallback when reranking cannot be performed. Time complexity: O(batch * width)
    for array allocation and filling. The function performs no I/O operations and
    is thread-safe. Sentinel values are chosen to be clearly invalid (minimum float,
    negative ID) so downstream code can easily detect and handle empty results.
    This allows the reranking pipeline to return consistent shapes even when no
    valid results are available.
    """
    filler = np.full((batch, width), np.finfo(np.float32).min, dtype=np.float32)
    identifiers = np.full((batch, width), -1, dtype=np.int64)
    return filler, identifiers


class FlatReranker:
    """Rerank ANN candidates using exact similarities from DuckDB embeddings."""

    def __init__(self, catalog: DuckDBCatalog, *, metric: str = "ip") -> None:
        self._catalog = catalog
        self._metric = metric

    def rerank(
        self,
        queries: np.ndarray,
        candidate_ids: np.ndarray,
        *,
        top_k: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return exact similarity scores and chunk ids.

        This method performs exact reranking of candidate chunk IDs by computing
        exact similarity scores between query vectors and candidate embeddings
        retrieved from the catalog. It delegates to the internal reranking
        implementation using the configured similarity metric (inner product or
        cosine similarity). The method returns the top-k reranked candidates
        sorted by exact similarity score.

        Parameters
        ----------
        queries : np.ndarray
            Query vectors with shape `(B, dim)` or `(dim,)` where B is the batch
            size and dim is the embedding dimension. Automatically reshaped to 2D
            if 1D. Dtype should be float32 or convertible to float32.
        candidate_ids : np.ndarray
            Candidate chunk identifiers with shape `(B, K')` where B matches the
            query batch size and K' is the number of candidates per query. Dtype
            should be int64 or convertible to int64. Negative IDs are treated as
            invalid and filtered out.
        top_k : int
            Number of top results to return per query after reranking. Must be
            positive. The method returns the top-k candidates sorted by exact
            similarity score (descending order).

        Returns
        -------
        np.ndarray
            Reranked similarity scores with shape `(B, top_k)` and dtype float32.
            Scores are exact similarity values (inner product or cosine similarity
            depending on configured metric) sorted in descending order (highest
            similarity first). Missing or invalid candidates are filled with
            minimum float32 value.
        np.ndarray
            Reranked chunk IDs with shape `(B, top_k)` and dtype int64. IDs
            correspond to the top-k scores and are aligned with the scores array.
            Missing or invalid candidates are filled with -1.
        """
        return _perform_exact_rerank(
            self._catalog,
            queries,
            candidate_ids,
            top_k=top_k,
            metric=self._metric,
        )


def exact_rerank(
    catalog: DuckDBCatalog,
    queries: np.ndarray,
    candidate_ids: np.ndarray,
    *,
    top_k: int,
    metric: str = "ip",
) -> tuple[np.ndarray, np.ndarray]:
    """Backward-compatible helper delegating to :class:`FlatReranker`.

    This function provides a backward-compatible interface to exact reranking
    functionality. It creates a FlatReranker instance with the specified metric
    and delegates to its rerank() method. This function maintains compatibility
    with existing code that calls exact_rerank() directly rather than using the
    FlatReranker class interface.

    Parameters
    ----------
    catalog : DuckDBCatalog
        DuckDB catalog instance providing embedding retrieval via
        get_embeddings_by_ids(). The catalog must contain embeddings for the
        candidate chunk IDs.
    queries : np.ndarray
        Query vectors with shape `(B, dim)` or `(dim,)` where B is the batch size
        and dim is the embedding dimension. Automatically reshaped to 2D if 1D.
        Dtype should be float32 or convertible to float32.
    candidate_ids : np.ndarray
        Candidate chunk identifiers with shape `(B, K')` where B matches the query
        batch size and K' is the number of candidates per query. Dtype should be
        int64 or convertible to int64. Negative IDs are treated as invalid.
    top_k : int
        Number of top results to return per query after reranking. Must be positive.
        The function returns the top-k candidates sorted by exact similarity score.
    metric : str, optional
        Similarity metric to use: "ip" (inner product) or "cos" (cosine similarity).
        Defaults to "ip". Cosine similarity normalizes both queries and candidates
        to unit length before computation.

    Returns
    -------
    np.ndarray
        Reranked similarity scores with shape `(B, top_k)` and dtype float32.
        Scores are exact similarity values sorted in descending order (highest
        similarity first). Missing or invalid candidates are filled with minimum
        float32 value.
    np.ndarray
        Reranked chunk IDs with shape `(B, top_k)` and dtype int64. IDs correspond
        to the top-k scores and are aligned with the scores array. Missing or
        invalid candidates are filled with -1.

    Notes
    -----
    This function is a convenience wrapper around FlatReranker for backward
    compatibility. New code should prefer using FlatReranker directly for better
    performance (avoids creating a new instance on each call). The function
        delegates all processing to FlatReranker.rerank() and returns the same
        results. Thread-safe if the catalog instance is thread-safe.
    """
    reranker = FlatReranker(catalog, metric=metric)
    return reranker.rerank(queries, candidate_ids, top_k=top_k)


__all__ = ["FlatReranker", "exact_rerank"]
