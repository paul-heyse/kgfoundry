"""Tests for vLLM configuration helpers."""

from __future__ import annotations

import pytest
from codeintel_rev.config.settings import VLLMConfig, VLLMEmbeddingMode

from tests._helpers import assertions


def test_vllm_config_pooling_type_property() -> None:
    """Embedding mode drives pooling literal and kwargs."""
    cfg = VLLMConfig(embedding_mode=VLLMEmbeddingMode.CLS)
    assertions.expect_equal(cfg.pooling_type, "CLS")
    kwargs = cfg.pooler_kwargs()
    assertions.expect_equal(kwargs["pooling_type"], "CLS")
    assertions.expect_true(kwargs["normalize"])


def test_vllm_config_warns_on_legacy_task() -> None:
    """Providing task raises a deprecation warning."""
    cfg = VLLMConfig(task="embed")
    with pytest.deprecated_call():
        _ = cfg.resolved_embedding_mode()
