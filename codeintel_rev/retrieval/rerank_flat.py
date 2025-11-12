"""Exact reranking utilities for FAISS candidates."""

from __future__ import annotations

from typing import Sequence, Tuple

import numpy as np

from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)


def exact_rerank(
    catalog: DuckDBCatalog,
    queries: np.ndarray,
    candidate_ids: np.ndarray,
    *,
    top_k: int,
    metric: str = "ip",
) -> Tuple[np.ndarray, np.ndarray]:
    """Hydrate embeddings for candidate ids and compute exact similarities.

    Parameters
    ----------
    catalog : DuckDBCatalog
        Catalog used to fetch embeddings by chunk identifier.
    queries : numpy.ndarray
        Query vectors shaped `(B, dim)` or `(dim,)`.
    candidate_ids : numpy.ndarray
        Candidate chunk identifiers shaped `(B, K')`.
    top_k : int
        Number of results to return per query after reranking.
    metric : str, optional
        Similarity metric. ``"ip"`` (inner product) by default. ``"cos"``
        will normalize both candidates and queries.

    Returns
    -------
    tuple[numpy.ndarray, numpy.ndarray]
        Tuple of (scores, ids) each shaped `(B, top_k)`.
    """
    if top_k <= 0:
        raise ValueError("top_k must be positive for rerank operations")

    query_mat = np.asarray(queries, dtype=np.float32)
    if query_mat.ndim == 1:
        query_mat = query_mat.reshape(1, -1)
    batch, dim = query_mat.shape

    candidates = np.asarray(candidate_ids, dtype=np.int64)
    if candidates.ndim != 2 or candidates.shape[0] != batch:
        raise ValueError(
            "candidate_ids must be shaped (batch, K') and aligned with query batch size"
        )

    valid_mask = candidates >= 0
    if not np.any(valid_mask):
        return (
            np.full((batch, min(top_k, candidates.shape[1])), np.finfo(np.float32).min),
            np.full((batch, min(top_k, candidates.shape[1])), -1, dtype=np.int64),
        )

    flat_ids = candidates.flatten()
    valid_ids = flat_ids[flat_ids >= 0]
    unique_ids = np.unique(valid_ids)
    id_list, emb_matrix = catalog.get_embeddings_by_ids(unique_ids.tolist())
    if not id_list:
        LOGGER.warning("Exact rerank skipped: no embeddings returned for %d ids", len(unique_ids))
        return (
            np.full((batch, min(top_k, candidates.shape[1])), np.finfo(np.float32).min),
            np.full((batch, min(top_k, candidates.shape[1])), -1, dtype=np.int64),
        )

    embedding_map: dict[int, np.ndarray] = {
        int(chunk_id): vec for chunk_id, vec in zip(id_list, emb_matrix, strict=True)
    }
    candidate_dim = emb_matrix.shape[1]
    if candidate_dim != dim:
        raise ValueError(f"Embedding dimension mismatch: {candidate_dim} != {dim}")

    filled = np.zeros_like(candidates, dtype=bool)
    vectors = np.zeros((batch, candidates.shape[1], dim), dtype=np.float32)
    k_prime = candidates.shape[1]
    for position, chunk_id in enumerate(flat_ids):
        if chunk_id < 0:
            continue
        vector = embedding_map.get(int(chunk_id))
        if vector is None:
            continue
        row = position // k_prime
        col = position % k_prime
        vectors[row, col, :] = vector
        filled[row, col] = True

    query_expanded = np.broadcast_to(query_mat[:, None, :], vectors.shape)
    if metric == "cos":
        query_norm = np.linalg.norm(query_expanded, axis=2, keepdims=True) + 1e-9
        cand_norm = np.linalg.norm(vectors, axis=2, keepdims=True) + 1e-9
        query_expanded = query_expanded / query_norm
        vectors = vectors / cand_norm

    sims = np.einsum("bid,bid->bi", vectors, query_expanded, optimize=True)
    sims[~filled] = np.finfo(np.float32).min
    k_eff = min(top_k, k_prime)
    if k_eff <= 0:
        raise ValueError("Effective top_k must be positive")

    topk_idx = np.argpartition(-sims, kth=k_eff - 1, axis=1)[:, :k_eff]
    row_index = np.arange(batch)[:, None]
    topk_scores = sims[row_index, topk_idx]
    order = np.argsort(-topk_scores, axis=1)
    topk_scores = topk_scores[row_index, order]
    topk_ids = candidates[row_index, topk_idx[row_index, order]]

    return topk_scores.astype(np.float32, copy=False), topk_ids.astype(np.int64, copy=False)


__all__ = ["exact_rerank"]
