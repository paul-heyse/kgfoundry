"""Exact reranking utilities for FAISS candidates."""

from __future__ import annotations

import numpy as np

from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)
_VECTOR_AXIS = 2
_CANDIDATE_MATRIX_NDIM = 2
_SIMILARITY_EPS = 1e-9


def exact_rerank(
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
    queries : numpy.ndarray
        Query vectors shaped `(B, dim)` or `(dim,)` where B is the batch size and
        dim is the embedding dimension. Automatically reshaped to 2D if 1D.
        Dtype should be float32 or convertible to float32.
    candidate_ids : numpy.ndarray
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
    numpy.ndarray
        Scores array with shape `(B, top_k)`, dtype float32. Exact similarity
        scores (inner product or cosine similarity) for the top-k reranked candidates.
        Scores are sorted in descending order (highest similarity first). Missing
        or invalid candidates are filled with minimum float32 value.
    numpy.ndarray
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

    query_mat = _normalize_queries(queries)
    candidates = _prepare_candidate_matrix(candidate_ids, query_mat.shape[0])
    if not np.any(candidates >= 0):
        return _empty_result(query_mat.shape[0], min(top_k, candidates.shape[1]))

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
    return _select_topk(candidates, similarities, k_eff)


def _normalize_queries(queries: np.ndarray) -> np.ndarray:
    query_mat = np.asarray(queries, dtype=np.float32)
    if query_mat.ndim == 1:
        query_mat = query_mat.reshape(1, -1)
    return query_mat


def _prepare_candidate_matrix(candidate_ids: np.ndarray, batch_size: int) -> np.ndarray:
    candidates = np.asarray(candidate_ids, dtype=np.int64)
    if candidates.ndim != _CANDIDATE_MATRIX_NDIM or candidates.shape[0] != batch_size:
        msg = "candidate_ids must be shaped (batch, K') and aligned with query batch size"
        raise ValueError(msg)
    return candidates


def _hydrate_embeddings(
    catalog: DuckDBCatalog, candidates: np.ndarray
) -> tuple[dict[int, np.ndarray], int]:
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
    row_index = np.arange(candidates.shape[0])[:, None]
    topk_idx = np.argpartition(-similarities, kth=top_k - 1, axis=1)[:, :top_k]
    topk_scores = similarities[row_index, topk_idx]
    order = np.argsort(-topk_scores, axis=1)
    ordered_scores = topk_scores[row_index, order]
    ordered_ids = candidates[row_index, topk_idx[row_index, order]]
    return ordered_scores.astype(np.float32, copy=False), ordered_ids.astype(np.int64, copy=False)


def _empty_result(batch: int, width: int) -> tuple[np.ndarray, np.ndarray]:
    filler = np.full((batch, width), np.finfo(np.float32).min, dtype=np.float32)
    identifiers = np.full((batch, width), -1, dtype=np.int64)
    return filler, identifiers


__all__ = ["exact_rerank"]
