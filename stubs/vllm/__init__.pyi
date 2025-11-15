from collections.abc import Sequence
from typing import Protocol

from vllm.config import PoolerConfig

class TokensPrompt(Protocol):
    prompt_token_ids: list[int]

class _EmbeddingOutput(Protocol):
    embedding: Sequence[float]

class _EmbeddingResult(Protocol):
    outputs: _EmbeddingOutput

class LLM:
    def __init__(self, *args: object, **kwargs: object) -> None: ...
    def embed(self, prompts: Sequence[TokensPrompt]) -> Sequence[_EmbeddingResult]: ...
    def shutdown(self) -> None: ...

__all__ = ["LLM", "PoolerConfig", "TokensPrompt"]
