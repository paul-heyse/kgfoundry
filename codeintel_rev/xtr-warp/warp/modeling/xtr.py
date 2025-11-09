"""XTR (Cross-encoder Transformer Retrieval) model components.

This module provides XTRTokenizer, XTRLinear, XTR model, and XTRCheckpoint
for using Google's XTR-base-en model with ColBERT-style encoding.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import torch
from huggingface_hub import hf_hub_download
from transformers import AutoModel, AutoTokenizer, logging
from warp.engine.constants import DOC_MAXLEN, QUERY_MAXLEN, TOKEN_EMBED_DIM
from warp.infra.config import ColBERTConfig
from warp.parameters import DEVICE


class XTRTokenizer:
    """Tokenizer wrapper for XTR models.

    Handles lowercasing and tokenization with padding and truncation.

    Parameters
    ----------
    tokenizer : AutoTokenizer
        HuggingFace tokenizer instance.
    """

    def __init__(self, tokenizer: AutoTokenizer) -> None:
        """Initialize XTRTokenizer with tokenizer.

        Parameters
        ----------
        tokenizer : AutoTokenizer
            HuggingFace tokenizer instance.
        """
        self.tokenizer = tokenizer

    def __call__(
        self, texts: str | list[str], length: int = QUERY_MAXLEN
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Tokenize texts with padding and truncation.

        Parameters
        ----------
        texts : str | list[str]
            Text(s) to tokenize.
        length : int
            Maximum sequence length (default: QUERY_MAXLEN).

        Returns
        -------
        tuple[torch.Tensor, torch.Tensor]
            Tuple of (input_ids, attention_mask).
        """
        if isinstance(texts, str):
            texts = [texts]

        tokenized = self.tokenizer(
            [text.lower() for text in texts],
            return_tensors="pt",
            padding="max_length",
            truncation=True,
            max_length=length,
        )
        input_ids = tokenized["input_ids"]
        attention_mask = tokenized["attention_mask"]

        return input_ids, attention_mask


# Source: https://huggingface.co/google/xtr-base-en/resolve/main/2_Dense/config.json
# Activation function is torch.nn.modules.linear.Identity
class XTRLinear(torch.nn.Module):
    """Linear projection layer for XTR models.

    Projects encoder outputs to embedding dimension. Activation function
    is Identity (no activation).

    Parameters
    ----------
    in_features : int
        Input dimension (default: 768).
    out_features : int
        Output dimension (default: 128).
    bias : bool
        Whether to use bias (default: False).
    """

    def __init__(
        self, in_features: int = 768, out_features: int = 128, *, _bias: bool = False
    ) -> None:
        """Initialize XTRLinear layer.

        Parameters
        ----------
        in_features : int
            Input dimension (default: 768).
        out_features : int
            Output dimension (default: 128).
        """
        super().__init__()
        self.linear = torch.nn.Linear(in_features, out_features, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass through linear layer.

        Parameters
        ----------
        x : torch.Tensor
            Input tensor.

        Returns
        -------
        torch.Tensor
            Projected tensor.
        """
        return self.linear(x)


class XTR(torch.nn.Module):
    """XTR model for encoding queries and documents.

    Combines encoder, linear projection, masking, and normalization for
    ColBERT-style dense retrieval.

    Parameters
    ----------
    tokenizer : XTRTokenizer
        Tokenizer instance.
    encoder : torch.nn.Module
        Encoder model (typically XTR encoder).
    """

    def __init__(self, tokenizer: XTRTokenizer, encoder: torch.nn.Module) -> None:
        """Initialize XTR model.

        Parameters
        ----------
        tokenizer : XTRTokenizer
            Tokenizer instance.
        encoder : torch.nn.Module
            Encoder model (typically XTR encoder).
        """
        super().__init__()
        self.tokenizer = tokenizer
        self.linear = XTRLinear().to(DEVICE)
        self.encoder = encoder.to(DEVICE)

    @property
    def device(self) -> torch.device:
        """Get device where model is located.

        Returns
        -------
        torch.device
            Model device.
        """
        return DEVICE

    def forward(
        self, input_ids: torch.Tensor, attention_mask: torch.Tensor
    ) -> torch.Tensor:
        """Forward pass through XTR model.

        Encodes input, projects to embedding dimension, applies masking,
        and normalizes.

        Parameters
        ----------
        input_ids : torch.Tensor
            Token IDs (batch_size x seq_len).
        attention_mask : torch.Tensor
            Attention mask (batch_size x seq_len).

        Returns
        -------
        torch.Tensor
            Normalized embeddings (batch_size x seq_len x dim).
        """
        q = self.encoder(input_ids, attention_mask).last_hidden_state
        q = self.linear(q)
        mask = (input_ids != 0).unsqueeze(2).float()
        q *= mask
        return torch.nn.functional.normalize(q, dim=2)


def build_xtr_model() -> XTR:
    """Build XTR model from pretrained checkpoint.

    Loads google/xtr-base-en model, encoder, tokenizer, and dense projection
    weights. Returns configured XTR instance.

    Returns
    -------
    XTR
        Configured XTR model instance.

    Notes
    -----
    Warning about uninitialized decoder weights is expected. Only encoder
    is used.
    """
    # NOTE Warning about unitialized decoder weights is to be expected.
    #      We only make use of the encoder anyways.
    logging.set_verbosity_error()
    model = AutoModel.from_pretrained("google/xtr-base-en", use_safetensors=True)

    tokenizer = XTRTokenizer(AutoTokenizer.from_pretrained("google/xtr-base-en"))
    xtr = XTR(tokenizer, model.encoder)

    # Source: https://huggingface.co/google/xtr-base-en/
    to_dense_path = hf_hub_download(
        repo_id="google/xtr-base-en", filename="2_Dense/pytorch_model.bin"
    )
    xtr.linear.load_state_dict(torch.load(to_dense_path))

    logging.set_verbosity_warning()
    return xtr


@dataclass(frozen=True)
class XTRDocumentEncodingOptions:
    """Options controlling XTR doc encoding."""

    keep_dims: bool | str = "flatten"
    to_cpu: bool = False
    showprogress: bool = False
    return_tokens: bool = False

    _ALLOWED_KEYS = frozenset({"keep_dims", "to_cpu", "showprogress", "return_tokens"})

    @classmethod
    def from_overrides(
        cls, overrides: Mapping[str, object]
    ) -> XTRDocumentEncodingOptions:
        """Build encoding options from keyword overrides.

        Constructs an XTRDocumentEncodingOptions instance from a mapping of keyword
        arguments. Validates that all override keys are allowed options.

        Parameters
        ----------
        overrides : Mapping[str, object]
            Dictionary of keyword arguments corresponding to XTRDocumentEncodingOptions fields.
            Valid keys are: keep_dims, to_cpu, showprogress, return_tokens.

        Returns
        -------
        XTRDocumentEncodingOptions
            Configured encoding options instance with overrides applied.

        Raises
        ------
        TypeError
            If any keys in overrides are not recognized as valid XTRDocumentEncodingOptions
            fields. This prevents typos and ensures type safety.
        """
        unexpected = set(overrides) - cls._ALLOWED_KEYS
        if unexpected:
            msg = f"Unexpected doc_from_text keyword(s): {sorted(unexpected)}"
            raise TypeError(msg)
        return cls(**{k: overrides[k] for k in overrides})


class XTRCheckpoint:
    """Checkpoint wrapper for XTR model inference.

    Provides ColBERT-compatible interface for encoding documents and queries
    using XTR model.

    Parameters
    ----------
    xtr : XTR
        XTR model instance.
    config : ColBERTConfig
        Configuration object.
    query_maxlen : int
        Maximum query length (default: QUERY_MAXLEN).
    """

    def __init__(
        self, xtr: XTR, config: ColBERTConfig, query_maxlen: int = QUERY_MAXLEN
    ) -> None:
        """Initialize XTRCheckpoint.

        Parameters
        ----------
        xtr : XTR
            XTR model instance.
        config : ColBERTConfig
            Configuration object.
        query_maxlen : int
            Maximum query length (default: QUERY_MAXLEN).
        """
        self.xtr = xtr
        self.config = config
        self.query_maxlen = query_maxlen

    def doc_from_text(
        self,
        docs: list[str],
        bsize: int | None = None,
        *,
        options: XTRDocumentEncodingOptions | None = None,
        **overrides: object,
    ) -> tuple[torch.Tensor, list[int]]:
        """Encode documents from text strings.

        Tokenizes and encodes documents, returning flattened embeddings
        and document lengths.

        Parameters
        ----------
        docs : list[str]
            Document texts to encode.
        bsize : int | None
            Batch size (required, cannot be None).
        options : XTRDocumentEncodingOptions | None
            Pre-configured encoding options. If None, options are built from overrides.
        **overrides : object
            Keyword arguments to override default encoding options. Valid keys are:
            keep_dims, to_cpu, showprogress, return_tokens. Ignored if options is provided.
        keep_dims : bool | str
            Must be "flatten" (default: True, but only "flatten" supported).
        to_cpu : bool
            Must be False (default: False).
        showprogress : bool
            Must be False (default: False).
        return_tokens : bool
            Must be False (default: False).

        Returns
        -------
        tuple[torch.Tensor, list[int]]
            Tuple of (flattened_embeddings, document_lengths).

        Raises
        ------
        TypeError
            If options and overrides are both provided, or if any override keys
            are not recognized as valid XTRDocumentEncodingOptions fields.
        ValueError
            If any parameter constraint is violated or config.doc_maxlen
            doesn't match DOC_MAXLEN.
        """
        if options is None:
            options = XTRDocumentEncodingOptions.from_overrides(overrides)
        elif overrides:
            msg = "Cannot pass keyword overrides when options is provided"
            raise TypeError(msg)

        keep_dims = options.keep_dims
        to_cpu = options.to_cpu
        showprogress = options.showprogress
        return_tokens = options.return_tokens

        if to_cpu:
            msg = "to_cpu must be False"
            raise ValueError(msg)
        if keep_dims != "flatten":
            msg = f"keep_dims must be 'flatten', got {keep_dims!r}"
            raise ValueError(msg)
        if showprogress:
            msg = "showprogress must be False"
            raise ValueError(msg)
        if return_tokens:
            msg = "return_tokens must be False"
            raise ValueError(msg)
        if self.config.doc_maxlen != DOC_MAXLEN:
            msg = (
                f"config.doc_maxlen must be {DOC_MAXLEN}, got {self.config.doc_maxlen}"
            )
            raise ValueError(msg)
        if bsize is None:
            msg = "bsize must be provided"
            raise ValueError(msg)

        input_ids, attention_mask = self.xtr.tokenizer(docs, self.config.doc_maxlen)
        text_batches = self._split_into_batches(input_ids, attention_mask, bsize)
        total_length = self._total_token_count(text_batches)
        batch_lengths = self._collect_batch_lengths(text_batches)
        batches = self._encode_text_batches(text_batches)
        flatten_embeddings = self._flatten_encoded_batches(
            batches=batches,
            batch_lengths=batch_lengths,
            total_length=total_length,
        )
        flattened_lengths = self._flatten_length_list(batch_lengths)
        return flatten_embeddings, flattened_lengths

    @staticmethod
    def _total_token_count(
        text_batches: list[tuple[torch.Tensor, torch.Tensor]],
    ) -> int:
        """Compute total token count across all batches.

        Returns
        -------
        int
            Total number of tokens across all batches.
        """
        return sum(
            int(torch.sum(attention_mask).item()) for _, attention_mask in text_batches
        )

    @staticmethod
    def _collect_batch_lengths(
        text_batches: list[tuple[torch.Tensor, torch.Tensor]],
    ) -> list[torch.Tensor]:
        """Collect per-batch token lengths used for flattening.

        Returns
        -------
        list[torch.Tensor]
            List of tensors containing per-document token lengths for each batch.
        """
        return [torch.sum(attention_mask, dim=1) for _, attention_mask in text_batches]

    def _encode_text_batches(
        self, text_batches: list[tuple[torch.Tensor, torch.Tensor]]
    ) -> list[torch.Tensor]:
        """Invoke the XTR model on each batch to produce embeddings.

        Returns
        -------
        list[torch.Tensor]
            List of embedding tensors, one per batch.
        """
        return [
            self.xtr(input_ids.to(DEVICE), attention_mask.to(DEVICE))
            for input_ids, attention_mask in text_batches
        ]

    @staticmethod
    def _flatten_encoded_batches(
        *,
        batches: list[torch.Tensor],
        batch_lengths: list[torch.Tensor],
        total_length: int,
    ) -> torch.Tensor:
        """Flatten batched embeddings into a single contiguous tensor.

        Returns
        -------
        torch.Tensor
            Flattened embeddings tensor with shape (total_length, TOKEN_EMBED_DIM).

        Raises
        ------
        ValueError
            If the total number of tokens processed does not match the expected tensor size.
        """
        flatten_embeddings = torch.zeros(
            (total_length, TOKEN_EMBED_DIM), dtype=torch.float32
        )
        num_tokens = 0
        for batch_embeds, batch_length in zip(batches, batch_lengths, strict=False):
            for embeddings, length in zip(batch_embeds, batch_length, strict=False):
                length_value = int(length)
                flatten_embeddings[num_tokens : num_tokens + length_value] = embeddings[
                    :length_value
                ].detach()
                num_tokens += length_value

        expected = flatten_embeddings.shape[0]
        if num_tokens != expected:
            msg = f"num_tokens ({num_tokens}) must equal flatten_embeddings.shape[0] ({expected})"
            raise ValueError(msg)

        return flatten_embeddings

    @staticmethod
    def _flatten_length_list(batch_lengths: list[torch.Tensor]) -> list[int]:
        """Convert batched length tensors into a flattened list.

        Returns
        -------
        list[int]
            Flattened list of document lengths.
        """
        return [int(length.item()) for lengths in batch_lengths for length in lengths]

    @staticmethod
    def _split_into_batches(
        ids: torch.Tensor, mask: torch.Tensor, bsize: int
    ) -> list[tuple[torch.Tensor, torch.Tensor]]:
        """Split token IDs and masks into batches.

        Parameters
        ----------
        ids : torch.Tensor
            Token ID tensor.
        mask : torch.Tensor
            Attention mask tensor.
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

    def cuda(self) -> XTRCheckpoint:
        """Move model to CUDA device.

        Returns
        -------
        XTRCheckpoint
            Self with model moved to CUDA.
        """
        self.xtr = self.xtr.cuda()
        return self

    def query_from_text(
        self,
        queries: list[str],
        bsize: int | None = None,
        context: list[str] | None = None,
        *,
        to_cpu: bool = False,
        full_length_search: bool = False,
    ) -> torch.Tensor:
        """Encode queries from text strings.

        Tokenizes and encodes queries, optionally batching.

        Parameters
        ----------
        queries : list[str]
            Query texts to encode.
        bsize : int | None
            Batch size (default: None, processes all at once).
        to_cpu : bool
            Whether to move output to CPU (default: False).
        context : list[str] | None
            Must be None (default: None).
        full_length_search : bool
            Must be False (default: False).

        Returns
        -------
        torch.Tensor
            Query embeddings tensor.

        Raises
        ------
        ValueError
            If context is not None or full_length_search is True.
        """
        if context is not None:
            msg = "context must be None"
            raise ValueError(msg)
        if full_length_search:
            msg = "full_length_search must be False"
            raise ValueError(msg)

        input_ids, attention_mask = self.xtr.tokenizer(queries, self.query_maxlen)
        if bsize is not None:
            batches = self._split_into_batches(input_ids, attention_mask, bsize)
            with torch.no_grad():
                if to_cpu:
                    return torch.cat(
                        [
                            self.xtr(
                                input_ids.to(self.xtr.device),
                                attention_mask.to(self.xtr.device),
                            ).cpu()
                            for input_ids, attention_mask in batches
                        ]
                    )
                return torch.cat(
                    [
                        self.xtr(
                            input_ids.to(self.xtr.device),
                            attention_mask.to(self.xtr.device),
                        ).cpu()
                        for input_ids, attention_mask in batches
                    ]
                )

        with torch.no_grad():
            encodings = self.xtr(
                input_ids.to(self.xtr.device), attention_mask.to(self.xtr.device)
            )

        if to_cpu:
            encodings = encodings.cpu()
        return encodings

    # NOTE "Hack" to support self.checkpoint.query_tokenizer.query_maxlen assignment
    @property
    def query_tokenizer(self) -> object:
        """Get placeholder query tokenizer for compatibility.

        Returns a placeholder object with query_maxlen attribute to support
        assignment patterns in existing code.

        Returns
        -------
        XTRQueryTokenizerPlaceholder
            Placeholder object with query_maxlen attribute.
        """

        class XTRQueryTokenizerPlaceholder:
            query_maxlen: int

        return XTRQueryTokenizerPlaceholder()
