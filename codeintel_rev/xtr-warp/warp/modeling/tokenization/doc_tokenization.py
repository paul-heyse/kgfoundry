"""Document tokenization for ColBERT models.

This module provides DocTokenizer for tokenizing document text with
special markers and padding/truncation.
"""

from __future__ import annotations

import torch
from warp.infra import ColBERTConfig
from warp.modeling.hf_colbert import class_factory
from warp.modeling.tokenization.utils import _sort_by_length, _split_into_batches
from warp.parameters import DEVICE


class DocTokenizer:
    """Tokenizes document text for ColBERT encoding.

    Handles tokenization with [D] marker, special tokens, and batching
    with length-based sorting.

    Parameters
    ----------
    config : ColBERTConfig
        Configuration specifying checkpoint and doc_maxlen.
    """

    def __init__(self, config: ColBERTConfig) -> None:
        """Initialize DocTokenizer with configuration.

        Parameters
        ----------
        config : ColBERTConfig
            Configuration specifying checkpoint and doc_maxlen.
        """
        hf_colbert = class_factory(config.checkpoint)
        self.tok = hf_colbert.raw_tokenizer_from_pretrained(config.checkpoint)

        self.config = config
        self.doc_maxlen = config.doc_maxlen

        self.D_marker_token, self.D_marker_token_id = (
            self.config.doc_token,
            self.tok.convert_tokens_to_ids(self.config.doc_token_id),
        )
        self.cls_token, self.cls_token_id = self.tok.cls_token, self.tok.cls_token_id
        self.sep_token, self.sep_token_id = self.tok.sep_token, self.tok.sep_token_id

    def tokenize(
        self, batch_text: list[str] | tuple[str, ...], *, add_special_tokens: bool = False
    ) -> list[list[str]]:
        """Tokenize batch of document texts.

        Parameters
        ----------
        batch_text : list[str] | tuple[str, ...]
            Batch of document texts to tokenize.
        add_special_tokens : bool
            Whether to add [CLS], [D], [SEP] tokens (default: False).

        Returns
        -------
        list[list[str]]
            List of tokenized sequences.

        Raises
        ------
        TypeError
            If batch_text is not list or tuple.
        """
        if type(batch_text) not in {list, tuple}:
            msg = f"batch_text must be list or tuple, got {type(batch_text).__name__}"
            raise TypeError(msg)

        tokens = [self.tok.tokenize(x, add_special_tokens=False).to(DEVICE) for x in batch_text]

        if not add_special_tokens:
            return tokens

        prefix, suffix = [self.cls_token, self.D_marker_token], [self.sep_token]
        return [prefix + lst + suffix for lst in tokens]

    def encode(
        self, batch_text: list[str] | tuple[str, ...], *, add_special_tokens: bool = False
    ) -> list[list[int]]:
        """Encode batch of document texts to token IDs.

        Parameters
        ----------
        batch_text : list[str] | tuple[str, ...]
            Batch of document texts to encode.
        add_special_tokens : bool
            Whether to add [CLS], [D], [SEP] token IDs (default: False).

        Returns
        -------
        list[list[int]]
            List of token ID sequences.

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

        prefix, suffix = [self.cls_token_id, self.D_marker_token_id], [self.sep_token_id]
        return [prefix + lst + suffix for lst in ids]

    def tensorize(
        self, batch_text: list[str] | tuple[str, ...], bsize: int | None = None
    ) -> (
        tuple[torch.Tensor, torch.Tensor]
        | tuple[list[tuple[torch.Tensor, torch.Tensor]], torch.Tensor]
    ):
        """Convert batch of texts to padded tensors.

        Tokenizes, pads to doc_maxlen, and optionally batches with
        length-based sorting.

        Parameters
        ----------
        batch_text : list[str] | tuple[str, ...]
            Batch of document texts.
        bsize : int | None
            Batch size for splitting (default: None, no batching).

        Returns
        -------
        tuple[torch.Tensor, torch.Tensor] | tuple[list, torch.Tensor]
            If bsize=None: (input_ids, attention_mask).
            If bsize specified: (batches, reverse_indices) for restoring order.

        Raises
        ------
        TypeError
            If batch_text is not list or tuple.
        """
        if type(batch_text) not in {list, tuple}:
            msg = f"batch_text must be list or tuple, got {type(batch_text).__name__}"
            raise TypeError(msg)

        # add placehold for the [D] marker
        batch_text = [". " + x for x in batch_text]

        obj = self.tok(
            batch_text,
            padding="longest",
            truncation="longest_first",
            return_tensors="pt",
            max_length=self.doc_maxlen,
        ).to(DEVICE)

        ids, mask = obj["input_ids"], obj["attention_mask"]

        # postprocess for the [D] marker
        ids[:, 1] = self.D_marker_token_id

        if bsize:
            ids, mask, reverse_indices = _sort_by_length(ids, mask, bsize)
            batches = _split_into_batches(ids, mask, bsize)
            return batches, reverse_indices

        return ids, mask
