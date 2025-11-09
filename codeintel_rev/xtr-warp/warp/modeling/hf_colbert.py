"""HuggingFace ColBERT model factory and wrappers.

This module provides factory functions and model classes for creating
ColBERT models from HuggingFace transformers, supporting various base
models and custom architectures.
"""

from __future__ import annotations

from typing import ClassVar

import torch
import transformers
from torch import nn
from transformers import (
    AutoConfig,
    AutoTokenizer,
    BertModel,
    BertPreTrainedModel,
    DebertaV2Model,
    DebertaV2PreTrainedModel,
    ElectraModel,
    ElectraPreTrainedModel,
    RobertaModel,
    RobertaPreTrainedModel,
    XLMRobertaConfig,
    XLMRobertaModel,
)
from transformers.dynamic_module_utils import get_class_from_dynamic_module
from warp.infra.config import ColBERTConfig
from warp.utils.utils import torch_load_dnn


class XLMRobertaPreTrainedModel(RobertaPreTrainedModel):
    """XLM-RoBERTa pretrained model wrapper.

    Overrides RobertaPreTrainedModel for XLM-RoBERTa compatibility.
    See superclass documentation for usage examples.
    """

    config_class = XLMRobertaConfig


base_class_mapping = {
    "roberta-base": RobertaPreTrainedModel,
    "google/electra-base-discriminator": ElectraPreTrainedModel,
    "xlm-roberta-base": XLMRobertaPreTrainedModel,
    "xlm-roberta-large": XLMRobertaPreTrainedModel,
    "bert-base-uncased": BertPreTrainedModel,
    "bert-large-uncased": BertPreTrainedModel,
    "microsoft/mdeberta-v3-base": DebertaV2PreTrainedModel,
    "bert-base-multilingual-uncased": BertPreTrainedModel,
}

model_object_mapping = {
    "roberta-base": RobertaModel,
    "google/electra-base-discriminator": ElectraModel,
    "xlm-roberta-base": XLMRobertaModel,
    "xlm-roberta-large": XLMRobertaModel,
    "bert-base-uncased": BertModel,
    "bert-large-uncased": BertModel,
    "microsoft/mdeberta-v3-base": DebertaV2Model,
    "bert-base-multilingual-uncased": BertModel,
}


transformers_module = dir(transformers)


def find_class_names(model_type: str, class_type: str) -> str | None:
    """Find transformer class name by model type.

    Searches transformers module for class matching model type and class type.

    Parameters
    ----------
    model_type : str
        Model type identifier (e.g., "roberta", "bert").
    class_type : str
        Class type suffix (e.g., "pretrainedmodel", "model").

    Returns
    -------
    str | None
        Class name if found, None otherwise.
    """
    model_type = model_type.replace("-", "").lower()
    for item in transformers_module:
        if model_type + class_type == item.lower():
            return item

    return None


def class_factory(name_or_path: str) -> type:
    """Create ColBERT model class from HuggingFace model name or path.

    Factory function that creates a dynamically subclassed ColBERT model
    from HuggingFace transformers, supporting standard models and custom
    architectures via auto_map.

    Parameters
    ----------
    name_or_path : str
        HuggingFace model name or path, or .dnn checkpoint path.

    Returns
    -------
    type
        HF_ColBERT class dynamically subclassed from appropriate base.

    Raises
    ------
    ValueError
        If pretrained or model class cannot be found, or if custom model
        doesn't have AutoModel in auto_map or model class doesn't end with "Model".
    """
    loaded_config = AutoConfig.from_pretrained(name_or_path, trust_remote_code=True)

    if getattr(loaded_config, "auto_map", None) is None:
        model_type = loaded_config.model_type
        pretrained_class = find_class_names(model_type, "pretrainedmodel")
        model_class = find_class_names(model_type, "model")

        if pretrained_class is not None:
            pretrained_class_object = getattr(transformers, pretrained_class)
        elif model_type == "xlm-roberta":
            pretrained_class_object = XLMRobertaPreTrainedModel
        elif base_class_mapping.get(name_or_path) is not None:
            pretrained_class_object = base_class_mapping.get(name_or_path)
        else:
            msg = (
                f"Could not find correct pretrained class for the model type "
                f"{model_type} in transformers library"
            )
            raise ValueError(msg)

        if model_class is not None:
            model_class_object = getattr(transformers, model_class)
        elif model_object_mapping.get(name_or_path) is not None:
            model_class_object = model_object_mapping.get(name_or_path)
        else:
            msg = (
                f"Could not find correct model class for the model type "
                f"{model_type} in transformers library"
            )
            raise ValueError(msg)
    else:
        if "AutoModel" not in loaded_config.auto_map:
            msg = "The custom model should have AutoModel class in the config.automap"
            raise ValueError(msg)
        model_class = loaded_config.auto_map["AutoModel"]
        if not model_class.endswith("Model"):
            msg = f"model_class must end with 'Model', got {model_class!r}"
            raise ValueError(msg)
        pretrained_class = model_class.replace("Model", "PreTrainedModel")
        model_class_object = get_class_from_dynamic_module(model_class, name_or_path)
        pretrained_class_object = get_class_from_dynamic_module(pretrained_class, name_or_path)

    class HFColBERT(pretrained_class_object):
        """
        Shallow wrapper around HuggingFace transformers. All new parameters
        should be defined at this level.

        This makes sure `{from,save}_pretrained` and `init_weights` are applied
        to new parameters correctly.
        """

        _keys_to_ignore_on_load_unexpected: ClassVar[list[str]] = [r"cls"]

        def __init__(self, config: AutoConfig, colbert_config: ColBERTConfig) -> None:
            super().__init__(config)

            self.config = config
            self.dim = colbert_config.dim
            self.linear = nn.Linear(config.hidden_size, colbert_config.dim, bias=False)
            setattr(self, self.base_model_prefix, model_class_object(config))

            self.init_weights()

        @property
        def lm(self) -> torch.nn.Module:
            """Get the language model base."""
            base_model_prefix = self.base_model_prefix
            return getattr(self, base_model_prefix)

        @classmethod
        def from_pretrained(cls, name_or_path: str, colbert_config: ColBERTConfig) -> type:
            if name_or_path.endswith(".dnn"):
                dnn = torch_load_dnn(name_or_path)
                base = dnn.get("arguments", {}).get("model", "bert-base-uncased")

                obj = super().from_pretrained(
                    base,
                    state_dict=dnn["model_state_dict"],
                    colbert_config=colbert_config,
                )
                obj.base = base

                return obj

            obj = super().from_pretrained(name_or_path, colbert_config=colbert_config)
            obj.base = name_or_path

            return obj

        @staticmethod
        def raw_tokenizer_from_pretrained(name_or_path: str) -> AutoTokenizer:
            if name_or_path.endswith(".dnn"):
                dnn = torch_load_dnn(name_or_path)
                base = dnn.get("arguments", {}).get("model", "bert-base-uncased")

                obj = AutoTokenizer.from_pretrained(base)
                obj.base = base

                return obj

            obj = AutoTokenizer.from_pretrained(name_or_path)
            obj.base = name_or_path

            return obj

    return HFColBERT
