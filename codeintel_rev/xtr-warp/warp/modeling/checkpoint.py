"""Checkpoint wrapper for easy ColBERT inference.

This module provides Checkpoint, a convenience wrapper around ColBERT models
for encoding queries and documents with automatic tokenization and mixed precision.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import torch
from tqdm import tqdm
from warp.engine.config import USE_CORE_ML, WARPRunConfig
from warp.engine.runtime.onnx_model import XTROnnxConfig, XTROnnxModel
from warp.engine.runtime.openvino_model import XTROpenVinoConfig, XTROpenVinoModel
from warp.engine.runtime.torchscript_model import (
    XTRTorchScriptConfig,
    XTRTorchScriptModel,
)
from warp.infra.config import ColBERTConfig
from warp.modeling.colbert import ColBERT
from warp.modeling.tokenization import DocTokenizer, QueryTokenizer
from warp.modeling.xtr import XTRCheckpoint, build_xtr_model
from warp.utils.amp import MixedPrecisionManager


@dataclass(frozen=True)
class DocumentEncodingOptions:
    """Options describing document encoding behavior."""

    keep_dims: bool | str = True
    to_cpu: bool = False
    showprogress: bool = False
    return_tokens: bool = False

    _ALLOWED_KEYS = frozenset({"keep_dims", "to_cpu", "showprogress", "return_tokens"})

    @classmethod
    def from_overrides(cls, overrides: Mapping[str, object]) -> DocumentEncodingOptions:
        """Build encoding options from keyword overrides.

        Constructs a DocumentEncodingOptions instance from a mapping of keyword
        arguments. Validates that all override keys are allowed options.

        Parameters
        ----------
        overrides : Mapping[str, object]
            Dictionary of keyword arguments corresponding to DocumentEncodingOptions fields.
            Valid keys are: keep_dims, to_cpu, showprogress, return_tokens.

        Returns
        -------
        DocumentEncodingOptions
            Configured encoding options instance with overrides applied.

        Raises
        ------
        TypeError
            If any keys in overrides are not recognized as valid DocumentEncodingOptions
            fields. This prevents typos and ensures type safety.
        """
        unexpected = set(overrides) - cls._ALLOWED_KEYS
        if unexpected:
            msg = f"Unexpected doc_from_text keyword(s): {sorted(unexpected)}"
            raise TypeError(msg)
        return cls(**{k: overrides[k] for k in overrides})


if USE_CORE_ML:
    from warp.engine.runtime.coreml_model import XTRCoreMLConfig, XTRCoreMLModel


class Checkpoint(ColBERT):
    """Easy inference interface for ColBERT models.

    Provides high-level methods for encoding queries and documents with
    automatic tokenization, batching, and mixed precision support.

    TODO: Add .cast() accepting [also] an object instance-of(Checkpoint) as first argument.

    Parameters
    ----------
    name : str
        Model name or path (e.g., "google/xtr-base-en").
    colbert_config : ColBERTConfig | None
        Optional configuration overrides (default: None).
    verbose : int
        Verbosity level (default: 3).
    warp_config : WARPRunConfig | None
        Optional WARP runtime configuration (default: None).

    Attributes
    ----------
    query_tokenizer : QueryTokenizer
        Tokenizer for query encoding.
    doc_tokenizer : DocTokenizer
        Tokenizer for document encoding.
    amp_manager : MixedPrecisionManager
        Mixed precision context manager.
    verbose : int
        Verbosity level.
    """

    def __new__(
        cls,
        name: str,
        colbert_config: ColBERTConfig | None = None,
        verbose: int = 3,
        warp_config: WARPRunConfig | None = None,
    ) -> Checkpoint | XTRCheckpoint:
        """Create Checkpoint or XTRCheckpoint instance based on model name.

        Factory method that returns XTRCheckpoint for "google/xtr-base-en" with
        appropriate runtime backend, or standard Checkpoint for other models.

        Parameters
        ----------
        cls
            Checkpoint class.
        name : str
            Model name or path (e.g., "google/xtr-base-en").
        colbert_config : ColBERTConfig | None
            Optional configuration overrides (default: None).
        verbose : int
            Verbosity level (default: 3).
        warp_config : WARPRunConfig | None
            Optional WARP runtime configuration (default: None).

        Returns
        -------
        Checkpoint | XTRCheckpoint
            Checkpoint instance (XTRCheckpoint for XTR models, Checkpoint otherwise).

        Raises
        ------
        AssertionError
            If XTR model name is provided but runtime config is invalid.
        """
        if name == "google/xtr-base-en":
            if warp_config is None or warp_config.runtime is None:
                xtr = build_xtr_model()
                config = colbert_config
                if warp_config is not None:
                    config = warp_config.colbert()
                return XTRCheckpoint(xtr, config)

            if isinstance(warp_config.runtime, XTRTorchScriptConfig):
                model = XTRTorchScriptModel(warp_config.runtime)
                return XTRCheckpoint(model, warp_config.colbert())

            if isinstance(warp_config.runtime, XTROnnxConfig):
                model = XTROnnxModel(warp_config.runtime)
                return XTRCheckpoint(model, warp_config.colbert())

            if isinstance(warp_config.runtime, XTROpenVinoConfig):
                model = XTROpenVinoModel(warp_config.runtime)
                return XTRCheckpoint(model, warp_config.colbert())

            if USE_CORE_ML and isinstance(warp_config.runtime, XTRCoreMLConfig):
                model = XTRCoreMLModel(warp_config.runtime)
                return XTRCheckpoint(model, warp_config.colbert())

            # We should never reach this point!
            raise AssertionError
        instance = super().__new__(cls)
        instance.__init__(name, colbert_config, verbose)
        return instance

    def __init__(
        self,
        name: str,
        colbert_config: ColBERTConfig | None = None,
        verbose: int = 3,
        _warp_config: WARPRunConfig | None = None,
    ) -> None:
        super().__init__(name, colbert_config)
        if self.training:
            msg = "training must be False for ColBERTCheckpoint"
            raise ValueError(msg)

        self.verbose = verbose

        self.query_tokenizer = QueryTokenizer(self.colbert_config, verbose=self.verbose)
        self.doc_tokenizer = DocTokenizer(self.colbert_config)

        self.amp_manager = MixedPrecisionManager(activated=True)

    def query(
        self, *args: object, to_cpu: bool = False, **kw_args: object
    ) -> torch.Tensor:
        """Encode query tokens into embeddings.

        Processes tokenized query input through ColBERT model with mixed precision.
        Delegates to parent ColBERT.query() method.

        Parameters
        ----------
        *args : object
            Positional arguments passed to ColBERT.query().
        to_cpu : bool
            Whether to move output to CPU (default: False).
        **kw_args : object
            Keyword arguments passed to ColBERT.query().

        Returns
        -------
        torch.Tensor
            Query embeddings tensor.
        """
        with torch.no_grad(), self.amp_manager.context():
            q = super().query(*args, **kw_args)
            return q.cpu() if to_cpu else q

    def doc(
        self,
        *args: object,
        to_cpu: bool = False,
        **kw_args: object,
    ) -> torch.Tensor | tuple[torch.Tensor, ...]:
        """Encode document tokens into embeddings.

        Processes tokenized document input through ColBERT model with mixed precision.
        Delegates to parent ColBERT.doc() method.

        Parameters
        ----------
        *args : object
            Positional arguments passed to ColBERT.doc().
        to_cpu : bool
            Whether to move output to CPU (default: False).
        **kw_args : object
            Keyword arguments passed to ColBERT.doc().

        Returns
        -------
        torch.Tensor | tuple[torch.Tensor, ...]
            Document embeddings tensor or tuple with additional outputs.
        """
        with torch.no_grad(), self.amp_manager.context():
            d = super().doc(*args, **kw_args)

            if to_cpu:
                return (d[0].cpu(), *d[1:]) if isinstance(d, tuple) else d.cpu()

            return d

    def query_from_text(
        self,
        queries: list[str],
        bsize: int | None = None,
        context: list[str] | None = None,
        *,
        to_cpu: bool = False,
        full_length_search: bool = False,
    ) -> torch.Tensor:
        """Encode query text strings into embeddings.

        Tokenizes and encodes query strings, optionally processing in batches
        and with context or full-length search.

        Parameters
        ----------
        queries : list[str]
            Query text strings to encode.
        bsize : int | None
            Batch size for processing (default: None, processes all at once).
        to_cpu : bool
            Whether to move output to CPU (default: False).
        context : list[str] | None
            Optional context strings for each query (default: None).
        full_length_search : bool
            Whether to use full-length search mode (default: False).

        Returns
        -------
        torch.Tensor
            Query embeddings tensor (num_queries x seq_len x dim).
        """
        if bsize:
            batches = self.query_tokenizer.tensorize(
                queries,
                context=context,
                bsize=bsize,
                full_length_search=full_length_search,
            )
            batches = [
                self.query(input_ids, attention_mask, to_cpu=to_cpu)
                for input_ids, attention_mask in batches
            ]
            return torch.cat(batches)

        input_ids, attention_mask = self.query_tokenizer.tensorize(
            queries, context=context, full_length_search=full_length_search
        )
        return self.query(input_ids, attention_mask)

    def doc_from_text(
        self,
        docs: list[str],
        bsize: int | None = None,
        *,
        options: DocumentEncodingOptions | None = None,
        **overrides: object,
    ) -> torch.Tensor | tuple[torch.Tensor, ...] | tuple[torch.Tensor, list[int], ...]:
        """Encode document text strings into embeddings.

        Tokenizes and encodes document strings with flexible output formatting.
        Supports batching, progress display, and various output shapes.

        Parameters
        ----------
        docs : list[str]
            Document text strings to encode.
        bsize : int | None
            Batch size for processing (default: None, processes all at once).
        options : DocumentEncodingOptions | None
            Pre-configured encoding options. If None, options are built from overrides.
        **overrides : object
            Keyword arguments to override default encoding options. Valid keys are:
            keep_dims, to_cpu, showprogress, return_tokens. Ignored if options is provided.
        keep_dims : bool | str
            Output shape control: True (3D tensor), False (list of tensors),
            "flatten" (2D tensor + doclens) (default: True).
        to_cpu : bool
            Whether to move output to CPU (default: False).
        showprogress : bool
            Whether to show progress bar (default: False).
        return_tokens : bool
            Whether to return tokenized text (default: False).

        Returns
        -------
        torch.Tensor | tuple[torch.Tensor, ...] | tuple[torch.Tensor, list[int], ...]
            Document embeddings. Shape depends on keep_dims:
            - True: (num_docs x max_seq_len x dim) tensor
            - False: list of (seq_len x dim) tensors
            - "flatten": (total_embeddings x dim) tensor + doclens list
            May include tokens if return_tokens=True.

        Raises
        ------
        TypeError
            If options and overrides are both provided, or if any override keys
            are not recognized as valid DocumentEncodingOptions fields.
        ValueError
            If keep_dims is not True, False, or "flatten".
        """
        if options is None:
            options = DocumentEncodingOptions.from_overrides(overrides)
        elif overrides:
            msg = "Cannot pass keyword overrides when options is provided"
            raise TypeError(msg)

        keep_dims = options.keep_dims
        to_cpu = options.to_cpu

        if keep_dims not in {True, False, "flatten"}:
            msg = f"keep_dims must be True, False, or 'flatten', got {keep_dims!r}"
            raise ValueError(msg)

        if bsize:
            text_batches, reverse_indices = self.doc_tokenizer.tensorize(
                docs, bsize=bsize
            )
            return self._doc_from_text_batched(
                text_batches=text_batches,
                reverse_indices=reverse_indices,
                options=options,
            )

        input_ids, attention_mask = self.doc_tokenizer.tensorize(docs)
        return self.doc(input_ids, attention_mask, keep_dims=keep_dims, to_cpu=to_cpu)

    def _doc_from_text_batched(
        self,
        text_batches: list[tuple[torch.Tensor, torch.Tensor]],
        reverse_indices: torch.Tensor,
        options: DocumentEncodingOptions,
    ) -> torch.Tensor | tuple[torch.Tensor, ...] | tuple[torch.Tensor, list[int], ...]:
        """Process batched document inputs using the configured options.

        Returns
        -------
        torch.Tensor | tuple[torch.Tensor, ...] | tuple[torch.Tensor, list[int], ...]
            Processed document embeddings with shape determined by options.keep_dims.
        """
        returned_text = self._prepare_returned_text(
            options.return_tokens, text_batches, reverse_indices
        )
        keep_dims_for_doc = (
            "return_mask" if options.keep_dims == "flatten" else options.keep_dims
        )
        batches = [
            self.doc(
                input_ids,
                attention_mask,
                keep_dims=keep_dims_for_doc,
                to_cpu=options.to_cpu,
            )
            for input_ids, attention_mask in tqdm(
                text_batches, disable=not options.showprogress
            )
        ]
        return self._finalize_batched_documents(
            keep_dims=options.keep_dims,
            batches=batches,
            reverse_indices=reverse_indices,
            returned_text=returned_text,
        )

    @staticmethod
    def _prepare_returned_text(
        *,
        return_tokens: bool,
        text_batches: list[tuple[torch.Tensor, torch.Tensor]],
        reverse_indices: torch.Tensor,
    ) -> list[str]:
        returned_text: list[str] = []
        if not return_tokens:
            return returned_text
        returned_text = [text for batch in text_batches for text in batch[0]]
        returned_text = [returned_text[idx] for idx in reverse_indices.tolist()]
        return [returned_text]

    def _finalize_batched_documents(
        self,
        *,
        keep_dims: bool | str,
        batches: list[tuple[torch.Tensor, torch.Tensor]],
        reverse_indices: torch.Tensor,
        returned_text: list[str],
    ) -> tuple[torch.Tensor, ...] | tuple[list[torch.Tensor], ...]:
        if keep_dims is True:
            d = _stack_3d_tensors(batches)
            return (d[reverse_indices], *returned_text)

        if keep_dims == "flatten":
            d, mask = zip(*batches, strict=True)
            combined_d = torch.cat(d)[reverse_indices]
            combined_mask = torch.cat(mask)[reverse_indices]
            doclens = combined_mask.squeeze(-1).sum(-1).tolist()
            flattened = combined_d.view(-1, self.colbert_config.dim)
            flattened = flattened[combined_mask.bool().flatten()].cpu()
            return (flattened, doclens, *returned_text)

        if keep_dims is not False:
            msg = f"keep_dims must be False at this point, got {keep_dims!r}"
            raise ValueError(msg)

        expanded = [elem for batch in batches for elem in batch]
        ordered = [expanded[idx] for idx in reverse_indices.tolist()]
        return (*ordered, *returned_text)

    def lazy_rank(self, queries: list[str], docs: list[str]) -> None:
        """Lazy ranking placeholder (not implemented).

        Pre-encodes queries and documents but does not perform scoring.
        Raises AssertionError indicating scoring is not implemented.

        Parameters
        ----------
        queries : list[str]
            Query text strings.
        docs : list[str]
            Document text strings.

        Raises
        ------
        AssertionError
            Always raised, as scoring is not implemented.
        """
        self.query_from_text(queries, bsize=128, to_cpu=True)
        self.doc_from_text(docs, bsize=128, to_cpu=True)

        msg = "Implement scoring"
        raise AssertionError(msg)

    def score(
        self,
        q: torch.Tensor,
        d: torch.Tensor,
        mask: torch.Tensor | None = None,
        lengths: torch.Tensor | None = None,
    ) -> torch.Tensor:
        """Score query-document pairs (not implemented).

        Placeholder method for computing ColBERT scores. Raises AssertionError
        indicating that colbert_score function should be called directly.

        Parameters
        ----------
        q : torch.Tensor
            Query embeddings (num_queries x seq_len x dim).
        d : torch.Tensor
            Document embeddings (num_docs x seq_len x dim).
        mask : torch.Tensor | None
            Optional attention mask (default: None).
        lengths : torch.Tensor | None
            Optional sequence lengths (default: None).

        Returns
        -------
        torch.Tensor
            Query-document similarity scores (not implemented).

        Raises
        ------
        AssertionError
            Always raised, as scoring should use colbert_score function.
        ValueError
            If both mask and lengths are provided.
        """
        msg = "Call colbert_score"
        raise AssertionError(msg)
        # EVENTUALLY: Just call the colbert_score function!

        if lengths is not None:
            if mask is not None:
                msg = "don't supply both mask and lengths"
                raise ValueError(msg)

            mask = torch.arange(d.size(1), device=self.device) + 1
            mask = mask.unsqueeze(0) <= lengths.to(self.device).unsqueeze(-1)

        scores = d @ q
        scores = scores if mask is None else scores * mask.unsqueeze(-1)
        scores = scores.max(1)

        return scores.values.sum(-1).cpu()


def _stack_3d_tensors(groups: list[torch.Tensor]) -> torch.Tensor:
    bsize = sum(x.size(0) for x in groups)
    maxlen = max(x.size(1) for x in groups)
    hdim = groups[0].size(2)

    output = torch.zeros(
        bsize, maxlen, hdim, device=groups[0].device, dtype=groups[0].dtype
    )

    offset = 0
    for x in groups:
        endpos = offset + x.size(0)
        output[offset:endpos, : x.size(1)] = x
        offset = endpos

    return output


"""
TODO:

def tokenize_and_encode(checkpoint, passages):
    embeddings, token_ids = checkpoint.doc_from_text(
        passages, bsize=128, keep_dims=False, showprogress=True, return_tokens=True
    )
    tokens = [
        checkpoint.doc_tokenizer.tok.convert_ids_to_tokens(ids.tolist())
        for ids in token_ids
    ]
    tokens = [
        tokens[: tokens.index("[PAD]") if "[PAD]" in tokens else -1]
        for tokens in tokens
    ]
    tokens = [[tok for tok in tokens if tok not in checkpoint.skiplist] for tokens in tokens]

    return embeddings, tokens

"""
