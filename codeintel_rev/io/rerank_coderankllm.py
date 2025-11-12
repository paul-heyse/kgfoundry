"""Listwise reranking using the CodeRankLLM checkpoint."""

from __future__ import annotations

import json
import threading
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, ClassVar, cast

from codeintel_rev.typing import gate_import
from kgfoundry_common.logging import get_logger

if TYPE_CHECKING:
    from transformers import AutoModelForCausalLM, PreTrainedTokenizerBase

LOGGER = get_logger(__name__)

_PROMPT_TEMPLATE = """You rank code snippets for the given QUERY.
Return ONLY a JSON list of chunk IDs ordered best-to-worst. Example: [12, 5, 9]

QUERY:
{query}

CANDIDATES:
{candidates}

JSON:
"""

_MAX_PREVIEW_CHARS = 400


class CodeRankListwiseReranker:
    """Listwise reranking helper built on CodeRankLLM."""

    _CACHE_LOCK: ClassVar[threading.Lock] = threading.Lock()
    _CACHE: ClassVar[
        dict[tuple[str, str], tuple[PreTrainedTokenizerBase, AutoModelForCausalLM]]
    ] = {}

    def __init__(
        self,
        *,
        model_id: str,
        device: str,
        max_new_tokens: int,
        temperature: float,
        top_p: float,
    ) -> None:
        self.model_id = model_id
        self.device = device
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.top_p = top_p

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
            # Keep original IDs for any candidates missing from model output
            missing = [cid for cid, _ in candidates if cid not in ordered_ids]
            return ordered_ids + missing
        LOGGER.warning("CodeRankLLM returned no JSON list; falling back to original order.")
        return [cid for cid, _ in candidates]

    def _ensure_model(self) -> tuple[PreTrainedTokenizerBase, AutoModelForCausalLM]:
        cache_key = (self.model_id, self.device)
        with self._CACHE_LOCK:
            cached = self._CACHE.get(cache_key)
            if cached:
                return cached
            transformers_module = gate_import(
                "transformers",
                "CodeRank listwise reranker (install `transformers`)",
            )
            tokenizer_cls = getattr(transformers_module, "AutoTokenizer", None)
            model_cls = getattr(transformers_module, "AutoModelForCausalLM", None)
            if tokenizer_cls is None or model_cls is None:
                msg = "transformers missing AutoTokenizer/AutoModelForCausalLM"
                raise RuntimeError(msg)
            tokenizer = cast(
                "PreTrainedTokenizerBase", tokenizer_cls.from_pretrained(self.model_id)
            )
            model = model_cls.from_pretrained(self.model_id)
            model.to(self.device)
            model.eval()
            pair = (tokenizer, cast("AutoModelForCausalLM", model))
            self._CACHE[cache_key] = pair
            LOGGER.info(
                "Loaded CodeRankLLM",
                extra={"model_id": self.model_id, "device": self.device},
            )
            return pair

    @staticmethod
    def _build_prompt(query: str, candidates: Sequence[tuple[int, str]]) -> str:
        formatted_candidates = "\n\n".join(
            f"Chunk ID: {cid}\nCode:\n{(snippet or '')[:_MAX_PREVIEW_CHARS]}"
            for cid, snippet in candidates
        )
        return _PROMPT_TEMPLATE.format(query=query.strip(), candidates=formatted_candidates)

    @staticmethod
    def _parse_rankings(text: str, valid_ids: set[int]) -> list[int]:
        snippet = text.strip()
        start = snippet.find("[")
        end = snippet.rfind("]")
        if start == -1 or end == -1 or end <= start:
            return []
        json_payload = snippet[start : end + 1]
        try:
            parsed = json.loads(json_payload)
        except json.JSONDecodeError:
            LOGGER.warning("Failed to parse CodeRankLLM JSON output.", extra={"output": snippet})
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
