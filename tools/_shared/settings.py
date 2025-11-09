"""Typed settings helpers for repository tooling.

The functions in this module provide a thin wrapper around
``pydantic_settings.BaseSettings`` so tooling modules can load strongly typed
configuration directly from environment variables. Validation errors are
surfaced as :class:`SettingsError` exceptions carrying RFC 9457 Problem Details
payloads, ensuring callers can emit structured responses and fail fast when
required configuration is missing.
"""

from __future__ import annotations

from collections.abc import Mapping
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING, Final, TypeVar

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from kgfoundry_common.errors.exceptions import SettingsError as CoreSettingsError
from tools._shared.problem_details import (
    ProblemDetailsParams,
    build_problem_details,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from tools._shared.problem_details import (
        JsonValue,
        ProblemDetailsDict,
    )

__all__: Final[list[str]] = [
    "SettingsError",
    "ToolRuntimeSettings",
    "get_runtime_settings",
    "load_settings",
]


SettingsT = TypeVar("SettingsT", bound=BaseSettings)


class SettingsError(CoreSettingsError):
    """Settings validation failure carrying Problem Details metadata."""

    def __init__(
        self,
        message: str,
        *,
        problem: ProblemDetailsDict,
        errors: Sequence[dict[str, JsonValue]],
        cause: Exception | None = None,
    ) -> None:
        self.problem: ProblemDetailsDict = dict(problem)
        self.validation_errors: tuple[dict[str, JsonValue], ...] = tuple(
            dict(err) for err in errors
        )
        super().__init__(
            message,
            errors=[dict(err) for err in self.validation_errors],
            cause=cause,
            context={"problem_details": dict(problem)},
        )


_SETTINGS_CACHE: dict[str, ToolRuntimeSettings] = {}


def load_settings(
    settings_factory: Callable[[], SettingsT] | type[SettingsT],
) -> SettingsT:
    """Instantiate settings via ``settings_factory`` with structured error handling.

    Parameters
    ----------
    settings_factory : Callable[[], SettingsT] | type[SettingsT]
        Zero-argument callable that returns a ``BaseSettings`` subclass.

    Returns
    -------
    SettingsT
        Validated settings instance.

    Raises
    ------
    SettingsError
        Raised when validation fails and the returned errors are converted to Problem Details.
    """
    try:
        return settings_factory()
    except ValidationError as exc:
        attr_name: object = getattr(settings_factory, "__name__", None)
        settings_name = (
            attr_name
            if isinstance(attr_name, str)
            else settings_factory.__class__.__name__
        )

        raw_errors: Sequence[object] = exc.errors()
        error_dicts: tuple[dict[str, JsonValue], ...] = tuple(
            _as_error_dict(err) for err in raw_errors
        )
        extensions: dict[str, JsonValue] = {
            "errors": list(error_dicts),
            "settings_class": settings_name,
        }
        problem = build_problem_details(
            ProblemDetailsParams(
                type="https://kgfoundry.dev/problems/tool-settings-invalid",
                title="Invalid tooling settings",
                status=500,
                detail="Failed to load tooling configuration",
                instance=f"urn:tool-settings:{settings_name}:invalid",
                extensions=extensions,
            )
        )
        message = "Failed to load tooling settings"
        raise SettingsError(
            message,
            problem=problem,
            errors=error_dicts,
            cause=exc,
        ) from exc


class ToolRuntimeSettings(BaseSettings):
    """Repository-wide runtime configuration for tooling helpers."""

    model_config = SettingsConfigDict(
        env_prefix="TOOLS_", case_sensitive=False, extra="ignore"
    )

    exec_allowlist: tuple[str, ...] = Field(
        default=(
            "python*",
            "uv",
            "git",
            "ruff",
            "pyright",
            "pytest",
            "doctoc",
            "docformatter",
            "spectral",
            "openspec",
            "dot",
            "neato",
            "pydeps",
            "pyreverse",
            "echo",
            "ls",
            "pwd",
            "sleep",
            "false",
        ),
        description="Glob patterns for executables allowed to run via tools._shared.proc",
    )
    exec_digests: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Optional SHA256 digests keyed by absolute executable path or basename. "
            "When present the resolved executable must match the configured digest before execution."
        ),
    )
    metrics_enabled: bool = Field(
        default=True,
        description="Enable Prometheus metrics emitted by tools._shared.metrics",
    )
    tracing_enabled: bool = Field(
        default=True,
        description="Enable OpenTelemetry spans emitted by tools._shared.metrics",
    )

    @field_validator("exec_allowlist", mode="before")
    @classmethod
    def _normalise_allowlist(cls, value: object) -> tuple[str, ...]:
        if value is None:
            default_field = cls.model_fields.get("exec_allowlist")
            if default_field is None:
                return ()
            default_value: object = getattr(default_field, "default", ())
            if isinstance(default_value, tuple):
                return tuple(str(part) for part in default_value)
            if isinstance(default_value, (list, set)):
                return tuple(str(part) for part in default_value)
            return ()
        if isinstance(value, str):
            tokens = [part.strip() for part in value.split(",") if part.strip()]
            return tuple(tokens)
        if isinstance(value, (list, tuple, set)):
            tokens = [str(part).strip() for part in value if str(part).strip()]
            return tuple(tokens)
        message = "exec_allowlist must be a comma-separated string or sequence"
        raise TypeError(message)

    @field_validator("exec_digests", mode="before")
    @classmethod
    def _normalise_exec_digests(cls, value: object) -> dict[str, str]:
        if value is None:
            return {}
        if isinstance(value, Mapping):
            return {
                str(key): str(val).strip().lower()
                for key, val in value.items()
                if str(val).strip()
            }
        if isinstance(value, str):
            entries: dict[str, str] = {}
            for token in value.split(","):
                if not token.strip():
                    continue
                if "=" not in token:
                    message = "exec_digests entries must be in 'key=sha256' format when provided as a string"
                    raise ValueError(message)
                key, digest = token.split("=", 1)
                entries[key.strip()] = digest.strip().lower()
            return entries
        message = (
            "exec_digests must be a mapping or comma-separated 'key=sha256' string"
        )
        raise TypeError(message)

    def is_allowed(self, executable: Path) -> bool:
        """Return ``True`` when ``executable`` matches the configured allow list.

        Parameters
        ----------
        executable : Path
            Executable path to evaluate.

        Returns
        -------
        bool
            ``True`` when ``executable`` is permitted, otherwise ``False``.
        """
        candidate = executable.name
        absolute = str(executable)
        for pattern in self.exec_allowlist:
            if Path(pattern).is_absolute() and absolute == pattern:
                return True
            if fnmatch(candidate, pattern):
                return True
        return False

    def expected_digest_for(self, executable: Path) -> str | None:
        """Return the expected SHA256 digest for ``executable`` when configured.

        Parameters
        ----------
        executable : Path
            Executable path to check.

        Returns
        -------
        str | None
            Expected digest if configured, otherwise None.
        """
        digest_map = self.exec_digests
        if not digest_map:
            return None

        absolute_key = executable.as_posix()
        digest = digest_map.get(absolute_key)
        if digest is not None:
            return digest
        return digest_map.get(executable.name)


def get_runtime_settings() -> ToolRuntimeSettings:
    """Return singleton runtime settings for tooling.

    Returns
    -------
    ToolRuntimeSettings
        Cached settings instance populated from environment variables.
    """
    cached = _SETTINGS_CACHE.get("default")
    if cached is None:

        def _factory() -> ToolRuntimeSettings:
            return ToolRuntimeSettings()

        cached = load_settings(_factory)
        _SETTINGS_CACHE["default"] = cached
    return cached


def _as_error_dict(error: object) -> dict[str, JsonValue]:
    """Coerce a validation error object into a JSON-serialisable dictionary.

    Parameters
    ----------
    error : object
        Validation error structure returned by Pydantic.

    Returns
    -------
    dict[str, JsonValue]
        JSON-compatible dictionary representation of ``error``.
    """
    if isinstance(error, dict):
        return {str(key): _to_jsonable(value) for key, value in error.items()}
    return {"detail": _to_jsonable(error)}


def _to_jsonable(value: object) -> JsonValue:
    """Convert ``value`` into a Problem Details-compatible JSON value.

    Parameters
    ----------
    value : object
        Arbitrary Python value emitted during validation.

    Returns
    -------
    JsonValue
        JSON-compatible representation of ``value``.
    """
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _to_jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, Path):
        return value.as_posix()
    return repr(value)
