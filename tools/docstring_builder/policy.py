"""Policy engine for enforcing docstring quality gates."""

from __future__ import annotations

import datetime as _dt
import os
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, cast

from tools.docstring_builder.plugins.dataclass_fields import collect_dataclass_field_names

if TYPE_CHECKING:
    from pathlib import Path

    from tools.docstring_builder.semantics import SemanticResult


class PolicyConfigurationError(RuntimeError):
    """Raised when policy configuration cannot be parsed."""


class PolicyAction(StrEnum):
    """Enumeration of supported policy actions."""

    ERROR = "error"
    WARN = "warn"
    AUTOFIX = "autofix"

    @classmethod
    def parse(cls, value: str) -> PolicyAction:
        """Parse ``value`` into a :class:`PolicyAction`.

        Parameters
        ----------
        value : str
            Policy action string (e.g., "error", "warn", "autofix").

        Returns
        -------
        PolicyAction
            Parsed policy action enum value.

        Raises
        ------
        PolicyConfigurationError
            If the value is not a valid policy action.
        """
        lowered = value.strip().lower()
        try:
            return cls(lowered)
        except ValueError as exc:
            message = f"Unknown policy action: {value}"
            raise PolicyConfigurationError(message) from exc


@dataclass(slots=True, frozen=True)
class PolicyException:
    """Represents an allowlisted violation."""

    symbol: str
    rule: str
    expires_on: _dt.date
    justification: str

    def is_active(self, today: _dt.date) -> bool:
        """Return ``True`` when the exception has not expired.

        Parameters
        ----------
        today : _dt.date
            Current date to compare against expiration.

        Returns
        -------
        bool
            True if exception is still active, False if expired.
        """
        return self.expires_on >= today


@dataclass(slots=True, frozen=True)
class PolicySettings:
    """Resolved policy configuration with precedence applied."""

    coverage_threshold: float = 0.9
    coverage_action: PolicyAction = PolicyAction.ERROR
    missing_params_action: PolicyAction = PolicyAction.ERROR
    missing_returns_action: PolicyAction = PolicyAction.ERROR
    missing_examples_action: PolicyAction = PolicyAction.WARN
    summary_mood_action: PolicyAction = PolicyAction.ERROR
    dataclass_parity_action: PolicyAction = PolicyAction.ERROR
    exceptions: list[PolicyException] = field(default_factory=list)

    def action_for(self, rule: str) -> PolicyAction:
        """Return the configured action for ``rule``.

        Parameters
        ----------
        rule : str
            Rule name (e.g., "coverage", "missing-params").

        Returns
        -------
        PolicyAction
            Configured action for the rule, or ERROR if not found.
        """
        mapping: dict[str, PolicyAction] = {
            "coverage": self.coverage_action,
            "missing-params": self.missing_params_action,
            "missing-returns": self.missing_returns_action,
            "missing-examples": self.missing_examples_action,
            "summary-mood": self.summary_mood_action,
            "dataclass-parity": self.dataclass_parity_action,
        }
        return mapping.get(rule, PolicyAction.ERROR)


@dataclass(slots=True, frozen=True)
class PolicyViolation:
    """Describes a policy violation detected during evaluation."""

    rule: str
    symbol: str
    action: PolicyAction
    message: str

    @property
    def fatal(self) -> bool:
        """Return ``True`` when the violation is considered fatal.

        Returns
        -------
        bool
            True if violation action is ERROR, False otherwise.
        """
        return self.action == PolicyAction.ERROR


@dataclass(slots=True, frozen=True)
class PolicyReport:
    """Summary of policy evaluation across the run."""

    coverage: float
    threshold: float
    violations: list[PolicyViolation]


_ACTION_KEY_ALIASES: Mapping[str, str] = {
    "coverage": "coverage_action",
    "coverage_action": "coverage_action",
    "missing_params": "missing_params_action",
    "missing_params_action": "missing_params_action",
    "missing_returns": "missing_returns_action",
    "missing_returns_action": "missing_returns_action",
    "missing_examples": "missing_examples_action",
    "missing_examples_action": "missing_examples_action",
    "summary_mood": "summary_mood_action",
    "summary_mood_action": "summary_mood_action",
    "dataclass_parity": "dataclass_parity_action",
    "dataclass_parity_action": "dataclass_parity_action",
}

_MIN_SUMMARY_WORD_LENGTH = 3


def _read_pyproject_policy(repo_root: Path) -> Mapping[str, object]:
    """Read policy configuration from pyproject.toml.

    Parameters
    ----------
    repo_root : Path
        Repository root directory.

    Returns
    -------
    Mapping[str, object]
        Policy configuration dictionary from pyproject.toml.
    """
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.exists():
        return {}
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    tool = data.get("tool", {})
    kgfoundry = tool.get("kgfoundry", {})
    docstrings = kgfoundry.get("docstrings", {})
    policy = docstrings.get("policy", {})
    return policy if isinstance(policy, Mapping) else {}


def _parse_exceptions(entries: Iterable[Mapping[str, object]]) -> list[PolicyException]:
    """Parse exception entries from configuration.

    Parameters
    ----------
    entries : Iterable[Mapping[str, object]]
        Exception entry dictionaries.

    Returns
    -------
    list[PolicyException]
        Parsed exception instances.

    Raises
    ------
    PolicyConfigurationError
        If exception entries are malformed.
    """
    parsed: list[PolicyException] = []
    for entry in entries:
        symbol = str(entry.get("symbol", "")).strip()
        rule = str(entry.get("rule", "missing-params")).strip() or "missing-params"
        expires_raw = entry.get("expires-on") or entry.get("expires_on")
        justification = str(entry.get("justification", "")).strip()
        if not symbol or not expires_raw:
            message = "Policy exception requires symbol and expires-on"
            raise PolicyConfigurationError(message)
        try:
            expires_on = _dt.date.fromisoformat(str(expires_raw))
        except ValueError as exc:  # pragma: no cover - defensive guard
            message = f"Invalid expires-on value: {expires_raw}"
            raise PolicyConfigurationError(message) from exc
        parsed.append(
            PolicyException(
                symbol=symbol,
                rule=rule,
                expires_on=expires_on,
                justification=justification,
            )
        )
    return parsed


def _normalized_key(key: str) -> str:
    """Normalize a configuration key name.

    Parameters
    ----------
    key : str
        Raw configuration key.

    Returns
    -------
    str
        Normalized key (lowercase, underscores instead of hyphens).
    """
    return key.strip().replace("-", "_").lower()


def _apply_mapping(settings: PolicySettings, mapping: Mapping[str, object]) -> None:
    """Apply configuration mapping to policy settings.

    Parameters
    ----------
    settings : PolicySettings
        Settings instance to modify.
    mapping : Mapping[str, object]
        Configuration key-value pairs.

    Raises
    ------
    PolicyConfigurationError
        If configuration values are invalid or keys are unknown.
    """
    for raw_key, value in sorted(mapping.items(), key=lambda item: str(item[0])):
        key = _normalized_key(str(raw_key))
        if key == "coverage_threshold":
            settings.coverage_threshold = float(str(value))
            continue
        if key in {"coverage_action", "coverage"}:
            settings.coverage_action = PolicyAction.parse(str(value))
            continue
        alias = _ACTION_KEY_ALIASES.get(key)
        if alias:
            setattr(settings, alias, PolicyAction.parse(str(value)))
            continue
        if key == "exceptions":
            if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
                settings.exceptions = _parse_exceptions(
                    cast("Iterable[Mapping[str, object]]", value)
                )
                continue
            message = "Policy exceptions must be an iterable of mappings"
            raise PolicyConfigurationError(message)
        message = f"Unknown policy key: {raw_key}"
        raise PolicyConfigurationError(message)


def _parse_override_pairs(raw: str) -> dict[str, str]:
    """Parse override key=value pairs from a string.

    Parameters
    ----------
    raw : str
        Comma-separated key=value pairs.

    Returns
    -------
    dict[str, str]
        Dictionary mapping normalized keys to values.

    Raises
    ------
    PolicyConfigurationError
        If override pairs are malformed.
    """
    overrides: dict[str, str] = {}
    for chunk in raw.split(","):
        if not chunk.strip():
            continue
        if "=" not in chunk:
            message = f"Invalid override '{chunk}'"
            raise PolicyConfigurationError(message)
        key, value = chunk.split("=", 1)
        overrides[key.strip().lower()] = value.strip()
    return overrides


def _apply_overrides(settings: PolicySettings, overrides: Mapping[str, str]) -> None:
    """Apply override values to policy settings.

    Parameters
    ----------
    settings : PolicySettings
        Settings instance to modify.
    overrides : Mapping[str, str]
        Override key-value pairs.

    Raises
    ------
    PolicyConfigurationError
        If override values are invalid or keys are unknown.
    """
    for raw_key, raw_value in overrides.items():
        key = _normalized_key(raw_key)
        if key in {"coverage", "coverage_threshold"}:
            settings.coverage_threshold = float(raw_value)
            continue
        if key == "coverage_action":
            settings.coverage_action = PolicyAction.parse(raw_value)
            continue
        alias = _ACTION_KEY_ALIASES.get(key)
        if alias:
            setattr(settings, alias, PolicyAction.parse(raw_value))
            continue
        message = f"Unknown policy override: {raw_key}"
        raise PolicyConfigurationError(message)


def load_policy_settings(
    repo_root: Path,
    *,
    cli_overrides: Mapping[str, str] | None = None,
    env: Mapping[str, str] | None = None,
) -> PolicySettings:
    """Load policy settings from configuration, environment, and CLI overrides.

    Parameters
    ----------
    repo_root : Path
        Repository root directory.
    cli_overrides : Mapping[str, str] | None, optional
        CLI override key-value pairs.
    env : Mapping[str, str] | None, optional
        Environment variable mapping (defaults to os.environ).

    Returns
    -------
    PolicySettings
        Loaded policy settings with precedence applied.
    """
    settings = PolicySettings()
    _apply_mapping(settings, _read_pyproject_policy(repo_root))
    env_mapping: Mapping[str, str] = env or os.environ
    env_raw = env_mapping.get("KGFOUNDRY_DOCSTRINGS_POLICY", "")
    if env_raw:
        _apply_overrides(settings, _parse_override_pairs(env_raw))
    if cli_overrides:
        _apply_overrides(settings, cli_overrides)
    return settings


class PolicyEngine:
    """Evaluate docstring semantics against configured policy rules.

    Parameters
    ----------
    settings : PolicySettings
        Policy configuration settings.
    """

    def __init__(self, settings: PolicySettings) -> None:
        self.settings = settings
        self.total_symbols = 0
        self.documented_symbols = 0
        self.violations: list[PolicyViolation] = []
        self._today = _dt.datetime.now(tz=_dt.UTC).date()
        self._dataclass_field_cache: dict[Path, dict[str, list[str]]] = {}

    def record(self, semantics: Iterable[SemanticResult]) -> None:
        """Record docstring semantics and evaluate them against policy rules."""
        for entry in semantics:
            self.total_symbols += 1
            documented = True
            missing_params = self._missing_parameter_names(entry)
            if missing_params and self._register_violation(
                rule="missing-params",
                symbol=entry.symbol.qname,
                detail=f"parameters missing descriptions: {', '.join(missing_params)}",
            ):
                documented = False
            if self._returns_missing_description(entry) and self._register_violation(
                rule="missing-returns",
                symbol=entry.symbol.qname,
                detail="return values missing descriptions",
            ):
                documented = False
            if self._examples_missing(entry) and self._register_violation(
                rule="missing-examples",
                symbol=entry.symbol.qname,
                detail="docstring lacks Examples section",
            ):
                documented = False
            if self._summary_not_imperative(entry) and self._register_violation(
                rule="summary-mood",
                symbol=entry.symbol.qname,
                detail="summary should use imperative mood",
            ):
                documented = False
            dataclass_detail = self._dataclass_parity_detail(entry)
            if dataclass_detail and self._register_violation(
                rule="dataclass-parity",
                symbol=entry.symbol.qname,
                detail=dataclass_detail,
            ):
                documented = False
            if not self._has_summary(entry):
                documented = False
            if documented:
                self.documented_symbols += 1

    def _register_violation(self, rule: str, symbol: str, detail: str) -> bool:
        """Register a violation, returning ``True`` if it was recorded.

        Parameters
        ----------
        rule : str
            Violation rule name.
        symbol : str
            Symbol qualified name.
        detail : str
            Violation detail message.

        Returns
        -------
        bool
            True if violation was recorded and is fatal, False otherwise.
        """
        exception = self._match_exception(symbol, rule)
        if exception and exception.is_active(self._today):
            return False
        action = self.settings.action_for(rule)
        if exception and not exception.is_active(self._today):
            detail = (
                f"{detail}; exception expired {exception.expires_on.isoformat()}"
                f" ({exception.justification or 'no justification provided'})"
            )
        message = f"{symbol}: {detail}"
        violation = PolicyViolation(rule=rule, symbol=symbol, action=action, message=message)
        self.violations.append(violation)
        return violation.fatal

    def _match_exception(self, symbol: str, rule: str) -> PolicyException | None:
        """Return an exception entry matching ``symbol`` and ``rule`` if present.

        Parameters
        ----------
        symbol : str
            Symbol qualified name.
        rule : str
            Rule name.

        Returns
        -------
        PolicyException | None
            Matching exception if found, None otherwise.
        """
        for exception in self.settings.exceptions:
            if exception.symbol == symbol and exception.rule == rule:
                return exception
        return None

    def finalize(self) -> PolicyReport:
        """Produce a final :class:`PolicyReport` summarising the evaluation.

        Returns
        -------
        PolicyReport
            Policy report with coverage, threshold, and violations.
        """
        coverage = 1.0 if self.total_symbols == 0 else self.documented_symbols / self.total_symbols
        if coverage + 1e-9 < self.settings.coverage_threshold:
            shortfall = (
                f"coverage {coverage:.1%} below threshold {self.settings.coverage_threshold:.1%}"
            )
            self._register_violation("coverage", "<aggregate>", shortfall)
        return PolicyReport(
            coverage=coverage,
            threshold=self.settings.coverage_threshold,
            violations=self.violations,
        )

    @staticmethod
    def _missing_parameter_names(entry: SemanticResult) -> list[str]:
        """Return parameter names missing descriptions for ``entry``.

        Parameters
        ----------
        entry : SemanticResult
            Semantic result to check.

        Returns
        -------
        list[str]
            List of parameter names missing descriptions.
        """
        missing: list[str] = []
        for parameter in entry.schema.parameters:
            description = parameter.description.strip()
            if not description or description.lower().startswith("todo"):
                missing.append(parameter.name)
        return missing

    @staticmethod
    def _returns_missing_description(entry: SemanticResult) -> bool:
        """Return ``True`` when any return entry lacks a useful description.

        Parameters
        ----------
        entry : SemanticResult
            Semantic result to check.

        Returns
        -------
        bool
            True if any return entry lacks a description, False otherwise.
        """
        for ret in entry.schema.returns:
            description = ret.description.strip()
            if not description or description.lower().startswith("todo"):
                return True
        return False

    @staticmethod
    def _examples_missing(entry: SemanticResult) -> bool:
        """Return ``True`` when the Examples section is empty or placeholder only.

        Parameters
        ----------
        entry : SemanticResult
            Semantic result to check.

        Returns
        -------
        bool
            True if examples are missing or empty, False otherwise.
        """
        if not entry.schema.examples:
            return True
        return not any(example.strip() for example in entry.schema.examples)

    @staticmethod
    def _summary_not_imperative(entry: SemanticResult) -> bool:
        """Return ``True`` when the summary appears non-imperative.

        Parameters
        ----------
        entry : SemanticResult
            Semantic result to check.

        Returns
        -------
        bool
            True if summary appears non-imperative, False otherwise.
        """
        summary = entry.schema.summary.strip()
        if not summary:
            return True
        first = summary.split()[0].lower()
        if first in {"this", "the"}:
            return True
        return bool(first.endswith("s") and len(first) > _MIN_SUMMARY_WORD_LENGTH)

    def _dataclass_parity_detail(self, entry: SemanticResult) -> str | None:
        """Return a violation detail when dataclass fields and docstrings drift.

        Parameters
        ----------
        entry : SemanticResult
            Semantic result to check.

        Returns
        -------
        str | None
            Violation detail message if drift detected, None otherwise.
        """
        if entry.symbol.kind != "class":
            return None
        decorators = {decorator.lower() for decorator in entry.symbol.decorators}
        if not any(
            decorator in decorators
            for decorator in (
                "dataclass",
                "dataclasses.dataclass",
                "attr.s",
                "attr.attrs",
                "attr.define",
                "attr.mutable",
                "attr.frozen",
                "attrs.define",
                "attrs.mutable",
                "attrs.frozen",
            )
        ):
            return None
        path = entry.symbol.filepath
        module = entry.symbol.module
        cache = self._dataclass_field_cache.get(path)
        if cache is None:
            cache = collect_dataclass_field_names(path, module)
            self._dataclass_field_cache[path] = cache
        actual = cache.get(entry.symbol.qname, [])
        documented = [parameter.name for parameter in entry.schema.parameters]
        if not actual:
            return None
        missing = [name for name in actual if name not in documented]
        extra = [name for name in documented if name not in actual]
        if not missing and not extra:
            return None
        details: list[str] = []
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        if extra:
            details.append(f"unexpected parameters: {', '.join(extra)}")
        return "; ".join(details)

    @staticmethod
    def _has_summary(entry: SemanticResult) -> bool:
        """Return ``True`` when ``entry`` includes a meaningful summary.

        Parameters
        ----------
        entry : SemanticResult
            Semantic result to check.

        Returns
        -------
        bool
            True if entry has a meaningful summary, False otherwise.
        """
        summary = entry.schema.summary.strip()
        if not summary:
            return False
        return not summary.lower().startswith("todo")


__all__ = [
    "PolicyAction",
    "PolicyConfigurationError",
    "PolicyEngine",
    "PolicyException",
    "PolicyReport",
    "PolicySettings",
    "PolicyViolation",
    "load_policy_settings",
]
