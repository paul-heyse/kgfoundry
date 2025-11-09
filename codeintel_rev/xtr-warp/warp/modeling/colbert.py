"""Core ColBERT model for encoding and scoring operations.

This module provides ColBERT, the main model class for training and inference,
with methods for encoding queries and documents, computing scores, and
handling interaction modes (colbert, flipr).
"""

from __future__ import annotations

import os
import pathlib
import string

import torch
from torch.utils.cpp_extension import load
from warp.infra.config.config import ColBERTConfig
from warp.modeling.base_colbert import BaseColBERT
from warp.search.strided_tensor import StridedTensor
from warp.utils.utils import flatten, print_message

# Tensor dimension constants
EXPECTED_QUERY_DOC_DIM = 3
EXPECTED_PACKED_DIM = 2
# Query maxlen for flipr interaction
FLIPR_QUERY_MAXLEN = 64


class ColBERT(BaseColBERT):
    """Core ColBERT model for encoding and scoring operations.

    Handles basic encoding and scoring operations in ColBERT. Used for training
    and provides query/document encoding, scoring, and interaction modes.

    Parameters
    ----------
    name : str
        Model name or path (default: "bert-base-uncased").
    colbert_config : ColBERTConfig | None
        Optional configuration overrides (default: None).

    Attributes
    ----------
    use_gpu : bool
        Whether GPU acceleration is enabled.
    skiplist : dict[int, bool] | None
        Token IDs to skip during masking (punctuation).
    pad_token : int
        Padding token ID.
    """

    def __init__(
        self,
        name: str = "bert-base-uncased",
        colbert_config: ColBERTConfig | None = None,
    ) -> None:
        super().__init__(name, colbert_config)
        self.use_gpu = colbert_config.total_visible_gpus > 0

        ColBERT.try_load_torch_extensions(self.use_gpu)

        if self.colbert_config.mask_punctuation:
            self.skiplist = {
                w: True
                for symbol in string.punctuation
                for w in [
                    symbol,
                    self.raw_tokenizer.encode(symbol, add_special_tokens=False)[0],
                ]
            }
        self.pad_token = self.raw_tokenizer.pad_token_id

    @classmethod
    def try_load_torch_extensions(cls, *, use_gpu: bool) -> None:
        """Load CUDA extensions for GPU-accelerated scoring.

        Loads segmented_maxsim_cpp extension if GPU is available and extensions
        haven't been loaded yet.

        Parameters
        ----------
        use_gpu : bool
            Whether to attempt loading GPU extensions.
        """
        if hasattr(cls, "loaded_extensions") or use_gpu:
            return

        print_message(
            "Loading segmented_maxsim_cpp extension "
            "(set COLBERT_LOAD_TORCH_EXTENSION_VERBOSE=True for more info)..."
        )
        segmented_maxsim_cpp = load(
            name="segmented_maxsim_cpp",
            sources=[
                str(pathlib.Path(__file__).parent.resolve() / "segmented_maxsim.cpp"),
            ],
            extra_cflags=["-O3"],
            verbose=os.getenv("COLBERT_LOAD_TORCH_EXTENSION_VERBOSE", "False") == "True",
        )
        cls.segmented_maxsim = segmented_maxsim_cpp.segmented_maxsim_cpp

        cls.loaded_extensions = True

    def forward(
        self, q: tuple[torch.Tensor, torch.Tensor], d: tuple[torch.Tensor, torch.Tensor]
    ) -> torch.Tensor | tuple[torch.Tensor, torch.Tensor]:
        """Forward pass for training with query-document pairs.

        Encodes query and document tokens, computes scores, and optionally
        computes in-batch negative loss.

        Parameters
        ----------
        q : tuple[torch.Tensor, torch.Tensor]
            Query input_ids and attention_mask.
        d : tuple[torch.Tensor, torch.Tensor]
            Document input_ids and attention_mask.

        Returns
        -------
        torch.Tensor | tuple[torch.Tensor, torch.Tensor]
            Scores tensor, or (scores, ib_loss) if use_ib_negatives is True.
        """
        q = self.query(*q)
        d, d_mask = self.doc(*d, keep_dims="return_mask")

        # Repeat each query encoding for every corresponding document.
        q_duplicated = q.repeat_interleave(self.colbert_config.nway, dim=0).contiguous()
        scores = self.score(q_duplicated, d, d_mask)

        if self.colbert_config.use_ib_negatives:
            ib_loss = self.compute_ib_loss(q, d, d_mask)
            return scores, ib_loss

        return scores

    def compute_ib_loss(
        self, q: torch.Tensor, d: torch.Tensor, d_mask: torch.Tensor
    ) -> torch.Tensor:
        """Compute in-batch negative loss for training.

        Computes cross-entropy loss using all documents in batch as negatives
        except the positive document for each query.

        Parameters
        ----------
        q : torch.Tensor
            Query embeddings (num_queries x seq_len x dim).
        d : torch.Tensor
            Document embeddings (num_docs x seq_len x dim).
        d_mask : torch.Tensor
            Document attention mask.

        Returns
        -------
        torch.Tensor
            Cross-entropy loss scalar.
        """
        # NOTE: Organize the code below! Quite messy.
        scores = (d.unsqueeze(0) @ q.permute(0, 2, 1).unsqueeze(1)).flatten(
            0, 1
        )  # query-major unsqueeze

        scores = colbert_score_reduce(scores, d_mask.repeat(q.size(0), 1, 1), self.colbert_config)

        nway = self.colbert_config.nway
        all_except_self_negatives = [
            list(range(qidx * d.size(0), qidx * d.size(0) + nway * qidx + 1))
            + list(range(qidx * d.size(0) + nway * (qidx + 1), qidx * d.size(0) + d.size(0)))
            for qidx in range(q.size(0))
        ]

        scores = scores[flatten(all_except_self_negatives)]
        scores = scores.view(q.size(0), -1)  # d.size(0) - self.colbert_config.nway + 1)

        labels = torch.arange(0, q.size(0), device=scores.device) * (self.colbert_config.nway)

        return torch.nn.CrossEntropyLoss()(scores, labels)

    def query(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        """Encode query tokens into normalized embeddings.

        Processes query tokens through BERT and linear projection, applies
        masking, and normalizes embeddings.

        Parameters
        ----------
        input_ids : torch.Tensor
            Query token IDs (batch_size x seq_len).
        attention_mask : torch.Tensor
            Query attention mask (batch_size x seq_len).

        Returns
        -------
        torch.Tensor
            Normalized query embeddings (batch_size x seq_len x dim).
        """
        input_ids, attention_mask = input_ids.to(self.device), attention_mask.to(self.device)
        q = self.bert(input_ids, attention_mask=attention_mask)[0]
        q = self.linear(q)

        mask = (
            torch.tensor(self.mask(input_ids, skiplist=[]), device=self.device).unsqueeze(2).float()
        )
        q *= mask

        return torch.nn.functional.normalize(q, p=2, dim=2)

    def doc(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor,
        *,
        keep_dims: bool | str = True,
    ) -> torch.Tensor | tuple[torch.Tensor, torch.Tensor] | list[torch.Tensor]:
        """Encode document tokens into normalized embeddings.

        Processes document tokens through BERT and linear projection, applies
        masking, and normalizes embeddings. Supports flexible output formats.

        Parameters
        ----------
        input_ids : torch.Tensor
            Document token IDs (batch_size x seq_len).
        attention_mask : torch.Tensor
            Document attention mask (batch_size x seq_len).
        keep_dims : bool | str
            Output format: True (3D tensor), False (list of 2D tensors),
            "return_mask" (3D tensor + mask) (default: True).

        Returns
        -------
        torch.Tensor | tuple[torch.Tensor, torch.Tensor] | list[torch.Tensor]
            Document embeddings. Format depends on keep_dims:
            - True: (batch_size x seq_len x dim) tensor
            - False: list of (seq_len x dim) tensors
            - "return_mask": (embeddings, mask) tuple

        Raises
        ------
        ValueError
            If keep_dims is not True, False, or "return_mask".
        """
        if keep_dims not in {True, False, "return_mask"}:
            msg = f"keep_dims must be True, False, or 'return_mask', got {keep_dims!r}"
            raise ValueError(msg)

        input_ids, attention_mask = input_ids.to(self.device), attention_mask.to(self.device)
        d = self.bert(input_ids, attention_mask=attention_mask)[0]
        d = self.linear(d)
        mask = (
            torch.tensor(self.mask(input_ids, skiplist=self.skiplist), device=self.device)
            .unsqueeze(2)
            .float()
        )
        d *= mask

        d = torch.nn.functional.normalize(d, p=2, dim=2)

        if keep_dims is False:
            d, mask = d.cpu(), mask.bool().cpu().squeeze(-1)
            d = [d_item[mask[idx]] for idx, d_item in enumerate(d)]

        elif keep_dims == "return_mask":
            return d, mask.bool()

        return d

    def score(self, q: torch.Tensor, d_padded: torch.Tensor, d_mask: torch.Tensor) -> torch.Tensor:
        """Compute ColBERT scores between queries and documents.

        Computes similarity scores using cosine or L2 similarity with maxsim
        interaction, depending on configuration.

        Parameters
        ----------
        q : torch.Tensor
            Query embeddings (num_queries x seq_len x dim).
        d_padded : torch.Tensor
            Padded document embeddings (num_docs x max_seq_len x dim).
        d_mask : torch.Tensor
            Document attention mask (num_docs x max_seq_len).

        Returns
        -------
        torch.Tensor
            Query-document similarity scores (num_queries x num_docs).

        Raises
        ------
        ValueError
            If similarity is "l2" but interaction is not "colbert".
        """
        if self.colbert_config.similarity == "l2":
            if self.colbert_config.interaction != "colbert":
                msg = (
                    "interaction must be 'colbert' when similarity is 'l2', "
                    f"got {self.colbert_config.interaction!r}"
                )
                raise ValueError(msg)
            return (
                (-1.0 * ((q.unsqueeze(2) - d_padded.unsqueeze(1)) ** 2).sum(-1))
                .max(-1)
                .values.sum(-1)
            )
        return colbert_score(q, d_padded, d_mask, config=self.colbert_config)

    def mask(
        self, input_ids: torch.Tensor, skiplist: list[int] | dict[int, bool]
    ) -> list[list[bool]]:
        """Generate attention mask excluding skip tokens and padding.

        Creates boolean mask indicating which tokens should be attended to,
        excluding tokens in skiplist and padding tokens.

        Parameters
        ----------
        input_ids : torch.Tensor
            Token IDs (batch_size x seq_len).
        skiplist : list[int] | dict[int, bool]
            Token IDs to skip (e.g., punctuation).

        Returns
        -------
        list[list[bool]]
            Boolean mask for each sequence (batch_size x seq_len).
        """
        return [
            [(x not in skiplist) and (x != self.pad_token) for x in d]
            for d in input_ids.cpu().tolist()
        ]


# NOTE: In Query/DocTokenizer, use colbert.raw_tokenizer


# NOTE: The masking below might also be applicable in the kNN part
def colbert_score_reduce(
    scores_padded: torch.Tensor, d_mask: torch.Tensor, config: ColBERTConfig
) -> torch.Tensor:
    """Reduce padded scores to query-document similarity scores.

    Applies maxsim reduction over document tokens, optionally using flipr
    interaction mode with top-k aggregation.

    Parameters
    ----------
    scores_padded : torch.Tensor
        Padded token-level scores (num_queries x num_docs x seq_len).
    d_mask : torch.Tensor
        Document attention mask (num_docs x seq_len).
    config : ColBERTConfig
        Configuration specifying interaction mode and parameters.

    Returns
    -------
    torch.Tensor
        Query-document similarity scores (num_queries x num_docs).

    Raises
    ------
    ValueError
        If interaction mode is not "colbert" or "flipr", or if query_maxlen
        is not 64 for flipr mode.
    """
    d_padding = ~d_mask.view(scores_padded.size(0), scores_padded.size(1)).bool()
    scores_padded[d_padding] = -9999
    scores = scores_padded.max(1).values

    if config.interaction not in {"colbert", "flipr"}:
        msg = f"config.interaction must be 'colbert' or 'flipr', got {config.interaction!r}"
        raise ValueError(msg)

    if config.interaction == "flipr":
        if config.query_maxlen != FLIPR_QUERY_MAXLEN:
            msg = (
                "query_maxlen must be 64 for flipr interaction (for now), "
                f"got {config.query_maxlen}"
            )
            raise ValueError(msg)

        k1 = config.query_maxlen // 2
        k2 = 8

        a = scores[:, : config.query_maxlen].topk(k1, dim=-1).values.sum(-1)
        b = 0

        if scores.size(1) - config.query_maxlen >= k2:
            b = scores[:, config.query_maxlen :].topk(k2, dim=-1).values.sum(1)

        return a + b

    return scores.sum(-1)


# NOTE: Wherever this is called, pass `config=`
def colbert_score(
    q: torch.Tensor,
    d_padded: torch.Tensor,
    d_mask: torch.Tensor,
    config: ColBERTConfig | None = None,
) -> torch.Tensor:
    """Compute ColBERT similarity scores between queries and documents.

    Computes token-level similarities and reduces to query-document scores.
    Supports broadcasting: if Q.size(0) is 1, compares with all documents;
    otherwise compares aligned query-document pairs.

    EVENTUALLY: Consider masking with -inf for the maxsim (or enforcing a ReLU).

    Parameters
    ----------
    q : torch.Tensor
        Query embeddings (1 | num_docs x seq_len x dim).
    d_padded : torch.Tensor
        Padded document embeddings (num_docs x max_seq_len x dim).
    d_mask : torch.Tensor
        Document attention mask (num_docs x max_seq_len).
    config : ColBERTConfig | None
        Configuration for interaction mode (default: None, creates new ColBERTConfig).

    Returns
    -------
    torch.Tensor
        Query-document similarity scores (num_queries x num_docs).

    Raises
    ------
    ValueError
        If tensor dimensions are invalid or Q.size(0) doesn't match D_padded.size(0).
    """
    if config is None:
        config = ColBERTConfig()
    use_gpu = config.total_visible_gpus > 0
    if use_gpu:
        q, d_padded, d_mask = q.cuda(), d_padded.cuda(), d_mask.cuda()

    if q.dim() != EXPECTED_QUERY_DOC_DIM:
        msg = f"q.dim() must be {EXPECTED_QUERY_DOC_DIM}, got {q.dim()} (q.size()={q.size()})"
        raise ValueError(msg)
    if d_padded.dim() != EXPECTED_QUERY_DOC_DIM:
        msg = (
            f"d_padded.dim() must be {EXPECTED_QUERY_DOC_DIM}, "
            f"got {d_padded.dim()} (d_padded.size()={d_padded.size()})"
        )
        raise ValueError(msg)
    if q.size(0) not in {1, d_padded.size(0)}:
        msg = (
            f"q.size(0) must be 1 or d_padded.size(0), got q.size(0)={q.size(0)}, "
            f"d_padded.size(0)={d_padded.size(0)}"
        )
        raise ValueError(msg)

    scores = d_padded @ q.to(dtype=d_padded.dtype).permute(0, 2, 1)

    return colbert_score_reduce(scores, d_mask, config)


def colbert_score_packed(
    q: torch.Tensor,
    d_packed: torch.Tensor,
    d_lengths: torch.Tensor,
    config: ColBERTConfig | None = None,
) -> torch.Tensor:
    """Compute ColBERT scores for a single query against packed documents.

    Parameters
    ----------
    q : torch.Tensor
        Query tensor (single query).
    d_packed : torch.Tensor
        Packed document tensor.
    d_lengths : torch.Tensor
        Lengths of each document in d_packed.
    config : ColBERTConfig | None
        Configuration object (default: None, creates new ColBERTConfig).

    Returns
    -------
    torch.Tensor
        Query-document similarity scores.

    Raises
    ------
    ValueError
        If q.dim() is not 2.
    """
    if config is None:
        config = ColBERTConfig()
    use_gpu = config.total_visible_gpus > 0

    if use_gpu:
        q, d_packed, d_lengths = q.cuda(), d_packed.cuda(), d_lengths.cuda()

    q = q.squeeze(0)

    if q.dim() != EXPECTED_PACKED_DIM:
        msg = f"q.dim() must be {EXPECTED_PACKED_DIM}, got {q.dim()} (q.size()={q.size()})"
        raise ValueError(msg)
    if d_packed.dim() != EXPECTED_PACKED_DIM:
        msg = (
            f"d_packed.dim() must be {EXPECTED_PACKED_DIM}, "
            f"got {d_packed.dim()} (d_packed.size()={d_packed.size()})"
        )
        raise ValueError(msg)

    scores = d_packed @ q.to(dtype=d_packed.dtype).T

    if use_gpu or config.interaction == "flipr":
        scores_padded, scores_mask = StridedTensor(
            scores, d_lengths, use_gpu=use_gpu
        ).as_padded_tensor()

        return colbert_score_reduce(scores_padded, scores_mask, config)
    return ColBERT.segmented_maxsim(scores, d_lengths)
