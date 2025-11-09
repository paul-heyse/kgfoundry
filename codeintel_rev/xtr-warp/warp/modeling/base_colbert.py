"""Base ColBERT model wrapper for WARP indexing and search.

This module provides BaseColBERT, a shallow wrapper around ColBERT model
parameters, configuration, and tokenizer for unified model management.
"""

from __future__ import annotations

import torch
from transformers import AutoTokenizer
from warp.infra.config import ColBERTConfig
from warp.modeling.hf_colbert import class_factory
from warp.parameters import DEVICE


class BaseColBERT(torch.nn.Module):
    """Shallow module wrapping ColBERT parameters, config, and tokenizer.

    Provides direct instantiation and saving of the model/colbert_config/tokenizer
    package. Like HuggingFace, evaluation mode is the default.

    Parameters
    ----------
    name_or_path : str
        Model name or path to checkpoint directory.
    colbert_config : ColBERTConfig | None
        Optional configuration overrides (default: None).

    Attributes
    ----------
    colbert_config : ColBERTConfig
        ColBERT configuration.
    name : str
        Model name.
    model
        Underlying ColBERT model instance.
    raw_tokenizer : AutoTokenizer
        HuggingFace tokenizer.
    """

    def __init__(self, name_or_path: str, colbert_config: ColBERTConfig | None = None) -> None:
        super().__init__()

        self.colbert_config = ColBERTConfig.from_existing(
            ColBERTConfig.load_from_checkpoint(name_or_path), colbert_config
        )
        self.name = self.colbert_config.model_name or name_or_path

        try:
            hf_colbert = class_factory(self.name)
        except (ImportError, AttributeError, TypeError):
            self.name = (
                "bert-base-uncased"  # NOTE: Double check that this is appropriate here in all cases
            )
            hf_colbert = class_factory(self.name)

        self.model = hf_colbert.from_pretrained(name_or_path, colbert_config=self.colbert_config)
        self.model.to(DEVICE)
        self.raw_tokenizer = AutoTokenizer.from_pretrained(name_or_path)

        self.eval()

    @property
    def device(self) -> torch.device:
        """Get the device where the model is located.

        Returns
        -------
        torch.device
            Model device.
        """
        return self.model.device

    @property
    def bert(self) -> torch.nn.Module:
        """Get the underlying BERT language model.

        Returns
        -------
        torch.nn.Module
            BERT model instance.
        """
        return self.model.lm

    @property
    def linear(self) -> torch.nn.Module:
        """Get the linear projection layer.

        Returns
        -------
        torch.nn.Module
            Linear layer instance.
        """
        return self.model.linear

    @property
    def score_scaler(self) -> torch.nn.Module:
        """Get the score scaling layer.

        Returns
        -------
        torch.nn.Module
            Score scaler instance.
        """
        return self.model.score_scaler

    def save(self, path: str) -> None:
        """Save model, tokenizer, and configuration to path.

        Persists the complete ColBERT checkpoint including model weights,
        tokenizer, and configuration files.

        Parameters
        ----------
        path : str
            Directory path for saving checkpoint.

        Raises
        ------
        ValueError
            If path ends with .dnn (reserved for deprecated format).
        """
        if path.endswith(".dnn"):
            msg = f"{path}: We reserve *.dnn names for the deprecated checkpoint format."
            raise ValueError(msg)

        self.model.save_pretrained(path)
        self.raw_tokenizer.save_pretrained(path)

        self.colbert_config.save_for_checkpoint(path)
