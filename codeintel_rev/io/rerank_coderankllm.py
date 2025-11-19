"""Listwise reranking using the CodeRankLLM checkpoint."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, cast

from codeintel_rev.runtime.imports import gate_import

if TYPE_CHECKING:
    from transformers import AutoModelForCausalLM, PreTrainedTokenizerBase

_PROMPT_TEMPLATE = """You rank code snippets for the given QUERY.
Return ONLY a JSON list of chunk IDs ordered best-to-worst. Example: [12, 5, 9]

QUERY:
{query}

CANDIDATES:
{candidates}

JSON:
"""

_MAX_PREVIEW_CHARS = 400


@dataclass(slots=True, frozen=True)
class CoderankLLMRerankerContext:
    """Dependency providers for CodeRank listwise reranker.

    Attributes
    ----------
    tokenizer_factory : Callable[[str], PreTrainedTokenizerBase]
        Factory function that creates a tokenizer from a model identifier.
        Used for dependency injection in tests.
    model_factory : Callable[[str], AutoModelForCausalLM]
        Factory function that creates a language model from a model identifier.
        Used for dependency injection in tests.
    """

    tokenizer_factory: Callable[[str], PreTrainedTokenizerBase]
    model_factory: Callable[[str], AutoModelForCausalLM]

    @classmethod
    def production(cls) -> CoderankLLMRerankerContext:
        """Return the production context using transformers imports.

        Returns
        -------
        CoderankLLMRerankerContext
            Context configured to load tokenizer/model via ``transformers``.
        """

        def _tokenizer(model_id: str) -> PreTrainedTokenizerBase:
            """Create AutoTokenizer instance from model ID.

            Parameters
            ----------
            model_id : str
                HuggingFace model identifier.

            Returns
            -------
            PreTrainedTokenizerBase
                Tokenizer instance loaded from model_id.

            Raises
            ------
            RuntimeError
                If transformers module doesn't expose AutoTokenizer.
            """
            transformers_module = gate_import(
                "transformers",
                "CodeRank listwise reranker (install `transformers`)",
            )
            tokenizer_cls = getattr(transformers_module, "AutoTokenizer", None)
            if tokenizer_cls is None:
                msg = "transformers missing AutoTokenizer"
                raise RuntimeError(msg)
            tokenizer = tokenizer_cls.from_pretrained(model_id)
            return cast("PreTrainedTokenizerBase", tokenizer)

        def _model(model_id: str) -> AutoModelForCausalLM:
            """Create AutoModelForCausalLM instance from model ID.

            Parameters
            ----------
            model_id : str
                HuggingFace model identifier.

            Returns
            -------
            AutoModelForCausalLM
                Model instance loaded from model_id.

            Raises
            ------
            RuntimeError
                If transformers module doesn't expose AutoModelForCausalLM.
            """
            transformers_module = gate_import(
                "transformers",
                "CodeRank listwise reranker (install `transformers`)",
            )
            model_cls = getattr(transformers_module, "AutoModelForCausalLM", None)
            if model_cls is None:
                msg = "transformers missing AutoModelForCausalLM"
                raise RuntimeError(msg)
            model = model_cls.from_pretrained(model_id)
            return cast("AutoModelForCausalLM", model)

        return cls(tokenizer_factory=_tokenizer, model_factory=_model)


@dataclass(slots=True, frozen=True)
class CodeRankGenerationSettings:
    """Generation parameters for CodeRank listwise reranker.

    Attributes
    ----------
    max_new_tokens : int
        Maximum number of tokens to generate. Must be positive.
    temperature : float
        Sampling temperature for generation. Higher values increase randomness.
        Must be positive.
    top_p : float
        Nucleus sampling parameter (top-p). Cumulative probability threshold for
        token sampling. Must be between 0.0 and 1.0.
    """

    max_new_tokens: int
    temperature: float
    top_p: float


class CodeRankListwiseReranker:
    """Listwise reranking helper built on CodeRankLLM.

    Parameters
    ----------
    model_id : str
        Hugging Face model identifier.
    device : str
        Device to run model on (e.g., "cuda", "cpu").
    settings : CodeRankGenerationSettings
        Generation settings (temperature, top_p, max_new_tokens).
    context : CoderankLLMRerankerContext | None, optional
        Optional context for dependency injection. If None, uses production context.
    """

    _CACHE_LOCK: ClassVar[threading.Lock] = threading.Lock()
    _CACHE: ClassVar[
        dict[tuple[str, str], tuple[PreTrainedTokenizerBase, AutoModelForCausalLM]]
    ] = {}

    def __init__(
        self,
        *,
        model_id: str,
        device: str,
        settings: CodeRankGenerationSettings,
        context: CoderankLLMRerankerContext | None = None,
    ) -> None:
        self.model_id = model_id
        self.device = device
        self.max_new_tokens = settings.max_new_tokens
        self.temperature = settings.temperature
        self.top_p = settings.top_p
        self._context = context or CoderankLLMRerankerContext.production()

    def rerank(self, query: str, candidates: Sequence[tuple[int, str]]) -> list[int]:
        """Return ordered chunk IDs ranked by CodeRankLLM.

        Parameters
        ----------
        query : str
            Natural language search query string.
        candidates : Sequence[tuple[int, str]]
            Sequence of (chunk_id, code_snippet) tuples to rerank. The code
            snippets are used as context for the LLM to determine relevance.

        Returns
        -------
        list[int]
            Ordered list of chunk IDs ranked by CodeRankLLM, highest score first.
            Length matches len(candidates).

        Raises
        ------
        RuntimeError
            If model generation fails or the model cannot produce output.
        """
        if not candidates:
            return []
        tokenizer, model = self._ensure_model()
        prompt = self._build_prompt(query, candidates)
        tokenizer_outputs = tokenizer(prompt, return_tensors="pt")
        inputs = {k: tensor.to(self.device) for k, tensor in tokenizer_outputs.items()}
        input_ids = inputs.get("input_ids")
        if input_ids is None:
            msg = "Tokenizer output missing input_ids for CodeRankLLM."
            raise RuntimeError(msg)
        generation_kwargs: dict[str, Any] = {
            "input_ids": input_ids,
            "max_new_tokens": self.max_new_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "do_sample": self.temperature > 0.0,
        }
        attention_mask = inputs.get("attention_mask")
        if attention_mask is not None:
            generation_kwargs["attention_mask"] = attention_mask
        try:
            output_ids = cast("Any", model).generate(**generation_kwargs)
        except Exception as exc:
            msg = f"CodeRankLLM generation failed: {exc}"
            raise RuntimeError(msg) from exc

        decoded = tokenizer.decode(output_ids[0], skip_special_tokens=True)
        ordered_ids = self._parse_rankings(decoded, {cid for cid, _ in candidates})
        if ordered_ids:
            missing = [cid for cid, _ in candidates if cid not in ordered_ids]
            return ordered_ids + missing
        return [cid for cid, _ in candidates]

    def _ensure_model(self) -> tuple[PreTrainedTokenizerBase, AutoModelForCausalLM]:
        """Ensure tokenizer and model are loaded and cached for current model_id/device.

        Returns
        -------
        tuple[PreTrainedTokenizerBase, AutoModelForCausalLM]
            Cached or newly loaded (tokenizer, model) pair.
        """
        cache_key = (self.model_id, self.device)
        with self._CACHE_LOCK:
            cached = self._CACHE.get(cache_key)
            if cached:
                return cached
            tokenizer = self._context.tokenizer_factory(self.model_id)
            model = self._context.model_factory(self.model_id)
            model_any = cast("Any", model)
            model_any.to(self.device)
            model_any.eval()
            pair = (tokenizer, cast("AutoModelForCausalLM", model_any))
            self._CACHE[cache_key] = pair
            return pair

    @staticmethod
    def _build_prompt(query: str, candidates: Sequence[tuple[int, str]]) -> str:
        """Build prompt string for CodeRankLLM from query and candidates.

        Parameters
        ----------
        query : str
            Natural language search query.
        candidates : Sequence[tuple[int, str]]
            Sequence of (chunk_id, code_snippet) tuples.

        Returns
        -------
        str
            Formatted prompt string ready for tokenization.
        """
        formatted_candidates = "\n\n".join(
            f"Chunk ID: {cid}\nCode:\n{(snippet or '')[:_MAX_PREVIEW_CHARS]}"
            for cid, snippet in candidates
        )
        return _PROMPT_TEMPLATE.format(query=query.strip(), candidates=formatted_candidates)

    @staticmethod
    def _parse_rankings(text: str, valid_ids: set[int]) -> list[int]:
        """Parse ranked chunk IDs from LLM output text.

        Parameters
        ----------
        text : str
            LLM generation output text containing JSON array of chunk IDs.
        valid_ids : set[int]
            Set of valid chunk IDs to filter parsed results.

        Returns
        -------
        list[int]
            Ordered list of chunk IDs parsed from text, filtered to valid_ids.
        """
        snippet = text.strip()
        start = snippet.find("[")
        end = snippet.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return []
        json_payload = snippet[start : end + 1]
        try:
            parsed = json.loads(json_payload)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        ordered: list[int] = []
        for value in parsed:
            try:
                cid = int(value)
            except (TypeError, ValueError):
                continue
            if cid in valid_ids and cid not in ordered:
                ordered.append(cid)
        return ordered
