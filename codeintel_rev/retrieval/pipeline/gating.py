"""Gating façade for orchestrating late-interaction stages."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from codeintel_rev.retrieval.gating import StageGateConfig as CoreStageGateConfig
from codeintel_rev.retrieval.gating import StageSignals, should_run_secondary_stage


@runtime_checkable
class ConvertibleNumber(Protocol):
    """Protocol describing values that can be converted to numeric types."""

    def __float__(self) -> float:
        """Return the value expressed as a float."""
        ...

    def __int__(self) -> int:
        """Return the value expressed as an integer."""
        ...


@runtime_checkable
class HybridSignalPayload(Protocol):
    """Protocol describing mapping-like payloads used for gating signals."""

    def get(self, key: str, default: object | None = None) -> object | None:
        """Return the raw payload value for ``key`` if present."""
        ...


@dataclass(slots=True, frozen=True)
class StageGateConfig:
    """Minimal configuration surface consumed by adapters."""

    min_candidates: int = 16
    margin_threshold: float = 0.2
    budget_ms: int = 750


@dataclass(slots=True, frozen=True)
class StageDecision:
    """Normalized gating decision."""

    should_run: bool
    reason: str
    notes: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class StageSignalFactory:
    """Validate and convert hybrid gating signals into :class:`StageSignals`."""

    payload: Mapping[str, object] | HybridSignalPayload

    def build(self) -> StageSignals:
        """Return a :class:`StageSignals` instance with validated values.

        Returns
        -------
        StageSignals
            Stage signal bundle with normalized numeric fields.
        """
        return StageSignals(
            candidate_count=self._require_int("candidate_count"),
            elapsed_ms=self._float_field("elapsed_ms", default=0.0),
            best_score=self._optional_float("top_score"),
            second_best_score=self._optional_float("second_score"),
        )

    def _require_int(self, field: str) -> int:
        """Return the integer value for ``field`` or raise if missing.

        Returns
        -------
        int
            Converted integer for the referenced field.

        Raises
        ------
        ValueError
            If the field is missing.
        """
        value = self.payload.get(field)
        if value is None:
            msg = f"{field} is required for gating"
            raise ValueError(msg)
        try:
            return _coerce_int(value, field)
        except TypeError as exc:
            raise ValueError(str(exc)) from exc

    def _float_field(self, field: str, *, default: float) -> float:
        """Return a float for ``field`` falling back to ``default``.

        Returns
        -------
        float
            Normalized float value for the specified field.

        Raises
        ------
        ValueError
            If the field value is not numeric.
        """
        value = self.payload.get(field, default)
        if value is None:
            return default
        try:
            return _coerce_float(value, field)
        except TypeError as exc:
            raise ValueError(str(exc)) from exc

    def _optional_float(self, field: str) -> float | None:
        """Return an optional float for ``field`` with ``None`` passthrough.

        Returns
        -------
        float | None
            Converted float or ``None`` when the field is absent.

        Raises
        ------
        ValueError
            If the field value is not numeric.
        """
        value = self.payload.get(field)
        if value is None:
            return None
        try:
            return _coerce_float(value, field)
        except TypeError as exc:
            raise ValueError(str(exc)) from exc


def decide_secondary_stage(
    *,
    signals: Mapping[str, object],
    config: StageGateConfig,
) -> StageDecision:
    """Run the core gating logic and normalize the result for adapters.

    Parameters
    ----------
    signals : Mapping[str, object]
        Stage signals containing candidate_count, elapsed_ms, top_score,
        and second_score.
    config : StageGateConfig
        Gating configuration with thresholds and budgets.

    Returns
    -------
    StageDecision
        Decision containing should_run flag, reason, and optional notes.
    """
    core_config = CoreStageGateConfig(
        min_candidates=config.min_candidates,
        margin_threshold=config.margin_threshold,
        budget_ms=config.budget_ms,
    )
    stage_signals = StageSignalFactory(signals).build()
    decision = should_run_secondary_stage(stage_signals, core_config)
    return StageDecision(
        should_run=decision.should_run,
        reason=decision.reason,
        notes=decision.notes,
    )


def _coerce_int(value: object, field: str) -> int:
    """Convert ``value`` to ``int`` and raise a descriptive error on failure.

    Returns
    -------
    int
        Integer representation of ``value``.

    Raises
    ------
    TypeError
        If the value cannot be converted to an integer.
    """
    if isinstance(value, bool):
        msg = f"{field} cannot be a boolean"
        raise TypeError(msg)
    if isinstance(value, (int, float, str, bytes, bytearray)):
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            msg = f"{field} must be an integer, got {value!r}"
            raise TypeError(msg) from exc
    msg = f"{field} must be numeric or string-convertible, got {type(value)!r}"
    raise TypeError(msg)


def _coerce_float(value: object, field: str) -> float:
    """Convert ``value`` to ``float`` and raise a descriptive error on failure.

    Returns
    -------
    float
        Converted float value.

    Raises
    ------
    TypeError
        If the value cannot be converted to a float.
    """
    if isinstance(value, bool):
        msg = f"{field} cannot be a boolean"
        raise TypeError(msg)
    if isinstance(value, (int, float, str, bytes, bytearray)):
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            msg = f"{field} must be a float, got {value!r}"
            raise TypeError(msg) from exc
    msg = f"{field} must be numeric or string-convertible, got {type(value)!r}"
    raise TypeError(msg)


__all__ = [
    "ConvertibleNumber",
    "HybridSignalPayload",
    "StageDecision",
    "StageGateConfig",
    "StageSignalFactory",
    "decide_secondary_stage",
]
