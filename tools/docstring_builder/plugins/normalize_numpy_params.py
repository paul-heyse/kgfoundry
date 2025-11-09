"""Plugin that normalizes parameter descriptions for NumPy style docstrings."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from tools.docstring_builder.plugins.base import (
    TransformerPlugin,
)

if TYPE_CHECKING:
    from tools.docstring_builder.plugins.base import (
        PluginContext,
        PluginStage,
    )
    from tools.docstring_builder.schema import ParameterDoc, ReturnDoc
    from tools.docstring_builder.semantics import SemanticResult


class NormalizeNumpyParamsPlugin(TransformerPlugin):
    """Ensure parameter descriptions follow a consistent style."""

    name: str = "normalize_numpy_params"
    stage: PluginStage = "transformer"

    def on_start(self, context: PluginContext) -> None:
        """Reset plugin state before processing begins (no-op)."""
        del self, context

    def on_finish(self, context: PluginContext) -> None:
        """Clean up plugin state after processing completes (no-op)."""
        del self, context

    def apply(self, context: PluginContext, payload: SemanticResult) -> SemanticResult:
        """Normalise parameter and return descriptions for ``payload``.

        Parameters
        ----------
        context : PluginContext
            Plugin context.
        payload : SemanticResult
            Semantic result to process.

        Returns
        -------
        SemanticResult
            Updated semantic result with normalized descriptions, or original if unchanged.
        """
        del self
        del context
        schema = payload.schema
        parameters = [NormalizeNumpyParamsPlugin._normalize_parameter(p) for p in schema.parameters]
        returns = [NormalizeNumpyParamsPlugin._normalize_return(entry) for entry in schema.returns]
        if parameters == schema.parameters and returns == schema.returns:
            return payload
        updated_schema = replace(schema, parameters=parameters, returns=returns)
        return replace(payload, schema=updated_schema)

    @staticmethod
    def _normalize_sentence(candidate: str, *, fallback: str) -> str:
        sentence = candidate.strip()
        if not sentence or sentence.lower().startswith("todo"):
            sentence = fallback
        if not sentence.endswith("."):
            sentence = f"{sentence}."
        if sentence and sentence[0].islower():
            sentence = f"{sentence[0].upper()}{sentence[1:]}"
        return sentence

    @classmethod
    def _normalize_parameter(cls, parameter: ParameterDoc) -> ParameterDoc:
        description = cls._normalize_sentence(
            parameter.description,
            fallback=f"Describe `{parameter.name}`.",
        )
        return replace(parameter, description=description)

    @classmethod
    def _normalize_return(cls, entry: ReturnDoc) -> ReturnDoc:
        description = cls._normalize_sentence(
            entry.description,
            fallback="Describe the returned value.",
        )
        return replace(entry, description=description)
