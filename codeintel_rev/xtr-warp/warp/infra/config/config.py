"""Configuration classes for WARP indexing and search.

This module provides RunConfig and ColBERTConfig, frozen dataclasses that
combine base configuration with runtime, resource, and model settings.
"""

from dataclasses import dataclass

from warp.infra.config.base_config import BaseConfig
from warp.infra.config.settings import (
    DocSettings,
    IndexingSettings,
    QuerySettings,
    ResourceSettings,
    RunSettings,
    SearchSettings,
    TokenizerSettings,
    TrainingSettings,
)


@dataclass(frozen=True)
class RunConfig(BaseConfig, RunSettings):
    """Configuration for WARP runtime execution.

    Combines BaseConfig with RunSettings for experiment management,
    GPU allocation, and distributed execution parameters.
    """


@dataclass(frozen=True)
class ColBERTConfig(
    RunSettings,
    ResourceSettings,
    DocSettings,
    QuerySettings,
    TrainingSettings,
    IndexingSettings,
    SearchSettings,
    BaseConfig,
    TokenizerSettings,
):
    """Complete configuration for ColBERT model training, indexing, and search.

    Combines all settings classes (run, resource, document, query, training,
    indexing, search, tokenizer) with BaseConfig for comprehensive model
    configuration management.
    """
