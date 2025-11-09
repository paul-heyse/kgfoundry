"""Tokenization utilities for ColBERT training.

This module provides functions for tensorizing training triples and
splitting sequences into batches.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import torch


class Tokenizer(Protocol):
    """Protocol for tokenizer objects with tensorize method."""

    def tensorize(
        self, batch_text: list[str] | tuple[str, ...], bsize: int | None = None
    ) -> (
        tuple[torch.Tensor, torch.Tensor]
        | tuple[list[tuple[torch.Tensor, torch.Tensor]], torch.Tensor]
    ):
        """Tensorize text into token IDs and masks.

        Parameters
        ----------
        batch_text : list[str] | tuple[str, ...]
            Batch of texts to tokenize.
        bsize : int | None
            Optional batch size for splitting.

        Returns
        -------
        tuple[torch.Tensor, torch.Tensor] | tuple[list[tuple[torch.Tensor, torch.Tensor]], torch.Tensor]
            Token IDs and attention masks, optionally batched.
        """
        ...


@dataclass(frozen=True)
class TokenizerPair:
    """Query/document tokenizer pair used for triple tensorization."""

    query: Tokenizer
    doc: Tokenizer


@dataclass(frozen=True)
class TensorizationSamples:
    """Inputs required to tensorize ColBERT training triples."""

    queries: list[str]
    passages: list[str]
    scores: list[float] | torch.Tensor
    batch_size: int | None
    nway: int


def tensorize_triples(
    tokenizers: TokenizerPair,
    samples: TensorizationSamples,
) -> list[
    tuple[
        tuple[torch.Tensor, torch.Tensor],
        tuple[torch.Tensor, torch.Tensor],
        list[float] | torch.Tensor,
    ]
]:
    """Tensorize training triples for ColBERT.

    Tokenizes queries and passages, then organizes them into batches
    along with scores.

    Parameters
    ----------
    tokenizers : TokenizerPair
        Pair of query and document tokenizers.
    samples : TensorizationSamples
        Samples containing queries, passages, scores, batch_size, and nway.

    Returns
    -------
    list[tuple[tuple[torch.Tensor, torch.Tensor], tuple[torch.Tensor, torch.Tensor], list[float] | torch.Tensor]]
        List of batches, each containing (query_ids, query_mask), (doc_ids, doc_mask), and scores.
    """
    q_ids, q_mask = tokenizers.query.tensorize(samples.queries)
    d_ids, d_mask = tokenizers.doc.tensorize(samples.passages)

    batch_size = samples.batch_size
    query_batches = split_into_batches(q_ids, q_mask, batch_size)
    doc_batches = split_into_batches(d_ids, d_mask, batch_size * samples.nway)
    score_batches = _build_score_batches(
        samples.scores, batch_size * samples.nway, len(doc_batches)
    )

    return _merge_batches(query_batches, doc_batches, score_batches)


def _build_score_batches(
    scores: list[float] | torch.Tensor, batch_size: int, num_batches: int
) -> list[list[float] | torch.Tensor]:
    if len(scores):
        return _split_into_batches2(scores, batch_size)
    return [[] for _ in range(num_batches)]


def _merge_batches(
    query_batches: list[tuple[torch.Tensor, torch.Tensor]],
    doc_batches: list[tuple[torch.Tensor, torch.Tensor]],
    score_batches: list[list[float] | torch.Tensor],
) -> list[
    tuple[
        tuple[torch.Tensor, torch.Tensor],
        tuple[torch.Tensor, torch.Tensor],
        list[float] | torch.Tensor,
    ]
]:
    """Pair query, document, and score batches into training triples.

    Returns
    -------
    list[tuple[tuple[torch.Tensor, torch.Tensor], tuple[torch.Tensor, torch.Tensor], list[float] | torch.Tensor]]
        List of triples containing (query_batch, doc_batch, score_batch).
    """
    merged: list[
        tuple[
            tuple[torch.Tensor, torch.Tensor],
            tuple[torch.Tensor, torch.Tensor],
            list[float] | torch.Tensor,
        ]
    ] = []
    for query_batch, doc_batch, score_batch in zip(
        query_batches, doc_batches, score_batches, strict=False
    ):
        merged.append((query_batch, doc_batch, score_batch))
    return merged


def sort_by_length(
    ids: torch.Tensor, mask: torch.Tensor, bsize: int
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Sort sequences by length for efficient batching.

    Sorts sequences by their actual length (mask sum) to minimize padding
    within batches. Returns reverse indices to restore original order.

    Parameters
    ----------
    ids : torch.Tensor
        Token ID tensor (batch_size x seq_len).
    mask : torch.Tensor
        Attention mask tensor (batch_size x seq_len).
    bsize : int
        Batch size threshold (if batch_size <= bsize, no sorting).

    Returns
    -------
    tuple[torch.Tensor, torch.Tensor, torch.Tensor]
        Tuple of (sorted_ids, sorted_mask, reverse_indices).
    """
    if ids.size(0) <= bsize:
        return ids, mask, torch.arange(ids.size(0))

    indices = mask.sum(-1).sort().indices
    reverse_indices = indices.sort().indices

    return ids[indices], mask[indices], reverse_indices


def split_into_batches(
    ids: torch.Tensor, mask: torch.Tensor, bsize: int
) -> list[tuple[torch.Tensor, torch.Tensor]]:
    """Split token IDs and masks into batches.

    Parameters
    ----------
    ids : torch.Tensor
        Token ID tensor (num_sequences x seq_len).
    mask : torch.Tensor
        Attention mask tensor (num_sequences x seq_len).
    bsize : int
        Batch size.

    Returns
    -------
    list[tuple[torch.Tensor, torch.Tensor]]
        List of (ids_batch, mask_batch) tuples.
    """
    return [
        (ids[offset : offset + bsize], mask[offset : offset + bsize])
        for offset in range(0, ids.size(0), bsize)
    ]


def _split_into_batches2(
    scores: list[float] | torch.Tensor, bsize: int
) -> list[list[float] | torch.Tensor]:
    """Split scores into batches.

    Parameters
    ----------
    scores : list[float] | torch.Tensor
        Scores to batch.
    bsize : int
        Batch size.

    Returns
    -------
    list[list[float] | torch.Tensor]
        List of score batches.
    """
    return [scores[offset : offset + bsize] for offset in range(0, len(scores), bsize)]
