"""Query tokenization for ColBERT models.

This module provides QueryTokenizer for tokenizing query text with
special markers, context handling, and full-length search support.
"""

from __future__ import annotations

import torch
from warp.infra import ColBERTConfig
from warp.modeling.hf_colbert import class_factory
from warp.modeling.tokenization.utils import _split_into_batches
from warp.parameters import DEVICE


class QueryTokenizer:
    """Tokenizes query text for ColBERT encoding.

    Handles tokenization with [Q] marker, context, full-length search,
    and padding to query_maxlen.

    Parameters
    ----------
    config : ColBERTConfig
        Configuration specifying checkpoint and query_maxlen.
    verbose : int
        Verbosity level (default: 3).
    """

    def __init__(self, config: ColBERTConfig, verbose: int = 3) -> None:
        """Initialize QueryTokenizer with configuration.

        Parameters
        ----------
        config : ColBERTConfig
            Configuration specifying checkpoint and query_maxlen.
        verbose : int
            Verbosity level (default: 3).
        """
        hf_colbert = class_factory(config.checkpoint)
        self.tok = hf_colbert.raw_tokenizer_from_pretrained(config.checkpoint)
        self.verbose = verbose

        self.config = config
        self.query_maxlen = config.query_maxlen
        self.background_maxlen = 512 - self.query_maxlen + 1  # NOTE: Make this configurable

        self.Q_marker_token, self.Q_marker_token_id = (
            config.query_token,
            self.tok.convert_tokens_to_ids(config.query_token_id),
        )
        self.cls_token, self.cls_token_id = self.tok.cls_token, self.tok.cls_token_id
        self.sep_token, self.sep_token_id = self.tok.sep_token, self.tok.sep_token_id
        self.mask_token, self.mask_token_id = (
            self.tok.mask_token,
            self.tok.mask_token_id,
        )
        self.pad_token, self.pad_token_id = self.tok.pad_token, self.tok.pad_token_id
        self.used = False

    def tokenize(
        self, batch_text: list[str] | tuple[str, ...], *, add_special_tokens: bool = False
    ) -> list[list[str]]:
        """Tokenize batch of query texts.

        Parameters
        ----------
        batch_text : list[str] | tuple[str, ...]
            Batch of query texts to tokenize.
        add_special_tokens : bool
            Whether to add [CLS], [Q], [SEP], and [MASK] tokens (default: False).

        Returns
        -------
        list[list[str]]
            List of tokenized sequences, padded to query_maxlen if add_special_tokens.

        Raises
        ------
        TypeError
            If batch_text is not list or tuple.
        """
        if type(batch_text) not in {list, tuple}:
            msg = f"batch_text must be list or tuple, got {type(batch_text).__name__}"
            raise TypeError(msg)

        tokens = [self.tok.tokenize(x, add_special_tokens=False) for x in batch_text]

        if not add_special_tokens:
            return tokens

        prefix, suffix = [self.cls_token, self.Q_marker_token], [self.sep_token]
        return [
            prefix + lst + suffix + [self.mask_token] * (self.query_maxlen - (len(lst) + 3))
            for lst in tokens
        ]

    def encode(
        self, batch_text: list[str] | tuple[str, ...], *, add_special_tokens: bool = False
    ) -> list[list[int]]:
        """Encode batch of query texts to token IDs.

        Parameters
        ----------
        batch_text : list[str] | tuple[str, ...]
            Batch of query texts to encode.
        add_special_tokens : bool
            Whether to add [CLS], [Q], [SEP], and [MASK] token IDs (default: False).

        Returns
        -------
        list[list[int]]
            List of token ID sequences, padded to query_maxlen if add_special_tokens.

        Raises
        ------
        TypeError
            If batch_text is not list or tuple.
        """
        if type(batch_text) not in {list, tuple}:
            msg = f"batch_text must be list or tuple, got {type(batch_text).__name__}"
            raise TypeError(msg)

        ids = self.tok(batch_text, add_special_tokens=False).to(DEVICE)["input_ids"]

        if not add_special_tokens:
            return ids

        prefix, suffix = [self.cls_token_id, self.Q_marker_token_id], [self.sep_token_id]
        return [
            prefix + lst + suffix + [self.mask_token_id] * (self.query_maxlen - (len(lst) + 3))
            for lst in ids
        ]

    def tensorize(
        self,
        batch_text: list[str] | tuple[str, ...],
        bsize: int | None = None,
        context: list[str] | None = None,
        *,
        full_length_search: bool = False,
    ) -> tuple[torch.Tensor, torch.Tensor] | list[tuple[torch.Tensor, torch.Tensor]]:
        """Convert batch of query texts to padded tensors.

        Tokenizes, pads to query_maxlen (or full length), handles context,
        and optionally batches.

        Parameters
        ----------
        batch_text : list[str] | tuple[str, ...]
            Batch of query texts.
        bsize : int | None
            Batch size for splitting (default: None, no batching).
        context : list[str] | None
            Optional context strings for each query (default: None).
        full_length_search : bool
            Whether to use full-length search (default: False).

        Returns
        -------
        tuple[torch.Tensor, torch.Tensor] | tuple[list, torch.Tensor]
            If bsize=None: (input_ids, attention_mask).
            If bsize specified: (batches, reverse_indices) for restoring order.

        Raises
        ------
        TypeError
            If batch_text is not list or tuple.
        ValueError
            If full_length_search=True with batch size > 1, or if context
            length doesn't match batch_text length.
        """
        if type(batch_text) not in {list, tuple}:
            msg = f"batch_text must be list or tuple, got {type(batch_text).__name__}"
            raise TypeError(msg)

        # add placehold for the [Q] marker
        batch_text = [". " + x for x in batch_text]

        # Full length search is only available for single inference (for now)
        # Batched full length search requires far deeper changes to the code base
        if full_length_search and not (isinstance(batch_text, list) and len(batch_text) == 1):
            msg = "full_length_search is only available for single inference (list with 1 element)"
            raise ValueError(msg)

        if full_length_search:
            # Tokenize each string in the batch
            un_truncated_ids = self.tok(batch_text, add_special_tokens=False).to(DEVICE)[
                "input_ids"
            ]
            # Get the longest length in the batch
            max_length_in_batch = max(len(x) for x in un_truncated_ids)
            # Set the max length
            max_length = self.max_len(max_length_in_batch)
        else:
            # Max length is the default max length from the config
            max_length = self.query_maxlen

        obj = self.tok(
            batch_text,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
            max_length=max_length,
        ).to(DEVICE)

        ids, mask = obj["input_ids"], obj["attention_mask"]

        # postprocess for the [Q] marker and the [MASK] augmentation
        ids[:, 1] = self.Q_marker_token_id
        ids[ids == self.pad_token_id] = self.mask_token_id

        if context is not None:
            if len(context) != len(batch_text):
                msg = (
                    f"len(context) ({len(context)}) must equal len(batch_text) ({len(batch_text)})"
                )
                raise ValueError(msg)

            obj_2 = self.tok(
                context,
                padding="longest",
                truncation=True,
                return_tensors="pt",
                max_length=self.background_maxlen,
            ).to(DEVICE)

            ids_2, mask_2 = (
                obj_2["input_ids"][:, 1:],
                obj_2["attention_mask"][:, 1:],
            )  # Skip the first [SEP]

            ids = torch.cat((ids, ids_2), dim=-1)
            mask = torch.cat((mask, mask_2), dim=-1)

        if self.config.attend_to_mask_tokens:
            mask[ids == self.mask_token_id] = 1
            if mask.sum().item() != mask.size(0) * mask.size(1):
                msg = (
                    f"mask.sum() ({mask.sum().item()}) must equal "
                    f"mask.size(0) * mask.size(1) ({mask.size(0) * mask.size(1)})"
                )
                raise ValueError(msg)

        if bsize:
            return _split_into_batches(ids, mask, bsize)

        if self.used is False:
            self.used = True

            (context is None) or context[0]
            if self.verbose > 1:
                pass

        return ids, mask

    # Ensure that query_maxlen <= length <= 500 tokens
    def max_len(self, length: int) -> int:
        """Ensure query length is within bounds.

        Clamps length between query_maxlen and 500 tokens.

        Parameters
        ----------
        length : int
            Input length.

        Returns
        -------
        int
            Length clamped between query_maxlen and 500.
        """
        return min(500, max(self.query_maxlen, length))
