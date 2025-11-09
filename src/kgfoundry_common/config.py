"""Configuration helpers shared across kgfoundry.

This module provides typed configuration management via pydantic_settings.BaseSettings,
with automatic environment variable parsing, validation, and caching.

Examples
--------
>>> from kgfoundry_common.config import load_config
>>> settings = load_config()
>>> settings.log_level  # doctest: +SKIP
'INFO'
"""

# [nav:section public-api]

from __future__ import annotations

import base64
from collections.abc import Mapping
from functools import lru_cache
from typing import (
    TYPE_CHECKING,
    ClassVar,
    Final,
    Literal,
    Self,
    TypedDict,
    Unpack,
    cast,
)

from pydantic import AliasChoices, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from kgfoundry_common.logging import get_logger
from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.types import JsonPrimitive, JsonValue

if TYPE_CHECKING:
    import functools
    from collections.abc import Sequence


__all__ = [
    "AppSettings",
    "JsonPrimitive",
    "JsonValue",
    "load_config",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))

logger = get_logger(__name__)

# Security constants
_MIN_SIGNING_KEY_BYTES: Final[int] = 32  # Minimum recommended key length


class ModelValidateOptions(TypedDict, total=False):
    """Options for model validation, encapsulating multiple parameters.

    This TypedDict groups validation parameters to reduce argument count in model_validate while
    maintaining compatibility with parent signature.
    """

    strict: bool | None
    extra: Literal["allow", "ignore", "forbid"] | None
    from_attributes: bool | None
    context: Mapping[str, object] | None
    by_alias: bool | None
    by_name: bool | None


def _compose_options(
    options: ModelValidateOptions | None,
    overrides: Mapping[str, object],
) -> ModelValidateOptions:
    """Return merged validation options prioritising ``overrides``.

    Parameters
    ----------
    options : ModelValidateOptions | None
        Base validation options to merge.
    overrides : Mapping[str, object]
        Override values that take precedence over ``options``.

    Returns
    -------
    ModelValidateOptions
        Merged validation options with overrides applied.
    """
    merged: dict[str, object] = {}
    if options:
        merged.update(options)
    merged.update(overrides)
    return cast("ModelValidateOptions", merged)


# [nav:anchor AppSettings]
class AppSettings(BaseSettings):
    """Application settings with environment variable support.

    This class uses pydantic_settings to load and validate configuration
    from environment variables. All fields are immutable (frozen=True) and
    self-documenting via Field descriptions.

    Security fields (HMAC signing key, subprocess/network timeouts) are
    optional but recommended. When provided, they enforce strict validation.

    Attributes
    ----------
    log_level : str
        Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL). Defaults to "INFO".
    log_format : str
        Logging format ('json' or 'text'). Defaults to "json".
    signing_key : str | None
        HMAC signing key for secure pickle (base64-encoded, ≥32 bytes recommended).
        Defaults to None.
    subprocess_timeout : int
        Default timeout for subprocess operations in seconds. Defaults to 300.
    request_timeout : int
        Default timeout for network requests in seconds. Defaults to 30.
    model_config : ClassVar[SettingsConfigDict]
        Pydantic model configuration (frozen=True, case_sensitive=False, populate_by_name=True).

    Examples
    --------
    >>> import os
    >>> # Set environment variable
    >>> os.environ["LOG_LEVEL"] = "DEBUG"
    >>> settings = AppSettings()
    >>> settings.log_level
    'DEBUG'

    >>> # Validate invalid log level
    >>> os.environ["LOG_LEVEL"] = "INVALID"
    >>> try:
    ...     AppSettings()  # doctest: +SKIP
    ... except Exception:
    ...     print("Validation failed for invalid log level")

    >>> # Security configuration with timeouts
    >>> os.environ["SUBPROCESS_TIMEOUT"] = "300"
    >>> os.environ["REQUEST_TIMEOUT"] = "30"
    >>> settings = AppSettings()  # doctest: +SKIP
    """

    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
        validation_alias=AliasChoices("LOG_LEVEL", "log_level"),
    )

    log_format: str = Field(
        default="json",
        description="Logging format ('json' or 'text')",
        validation_alias=AliasChoices("LOG_FORMAT", "log_format"),
    )

    signing_key: str | None = Field(
        default=None,
        description="HMAC signing key for secure pickle (base64-encoded, ≥32 bytes recommended)",
        validation_alias=AliasChoices("SIGNING_KEY", "signing_key"),
    )

    subprocess_timeout: int = Field(
        default=300,
        description="Default timeout for subprocess operations in seconds",
        validation_alias=AliasChoices("SUBPROCESS_TIMEOUT", "subprocess_timeout"),
        ge=1,
        le=3600,
    )

    request_timeout: int = Field(
        default=30,
        description="Default timeout for network requests in seconds",
        validation_alias=AliasChoices("REQUEST_TIMEOUT", "request_timeout"),
        ge=1,
        le=3600,
    )

    model_config: ClassVar[SettingsConfigDict] = {
        "frozen": True,
        "case_sensitive": False,
        "populate_by_name": True,
    }

    @classmethod
    def model_validate(
        cls,
        obj: object,
        *,
        options: ModelValidateOptions | None = None,
        **kwargs: Unpack[ModelValidateOptions],
    ) -> Self:
        """Validate ``obj`` returning ``cls`` while normalising pydantic errors.

        This method overrides the parent signature to normalize ValidationError
        exceptions. The many parameters are required to match the parent API,
        but internal logic is encapsulated in helper functions.

        Parameters
        ----------
        obj : object
            Object to validate.
        options : ModelValidateOptions | None
            Preconfigured validation options applied before ``kwargs`` overrides.
        **kwargs : Unpack[ModelValidateOptions]
            Validation parameters forwarded directly to :mod:`pydantic` and
            merged with ``options``.

        Returns
        -------
        Self
            Validated instance.

        Notes
        -----
        Validation errors are normalised and re-raised as :exc:`ValueError` by
        the internal validation helper.
        """
        merged = _compose_options(options, kwargs)
        return cls._validate_with_options(obj, merged)

    @classmethod
    def _validate_with_options(cls, obj: object, options: ModelValidateOptions) -> Self:
        """Encapsulate validation logic with reduced parameter count.

        Parameters
        ----------
        obj : object
            Object to validate.
        options : ModelValidateOptions
            Validation options dictionary.

        Returns
        -------
        Self
            Validated instance.

        Raises
        ------
        ValueError
            If validation fails with normalized error message.
        """
        try:
            return super().model_validate(
                obj,
                strict=options.get("strict"),
                extra=options.get("extra"),
                from_attributes=options.get("from_attributes"),
                context=options.get("context"),
                by_alias=options.get("by_alias"),
                by_name=options.get("by_name"),
            )
        except ValidationError as exc:
            message = _format_validation_error(exc)
            raise ValueError(message) from exc

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        """Validate log level is one of the standard levels.

        Parameters
        ----------
        value : str
            Log level to validate.

        Returns
        -------
        str
            Validated log level (uppercase).

        Raises
        ------
        ValueError
            If log level is not valid.
        """
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        level_upper = value.upper()
        if level_upper not in valid_levels:
            msg = f"Invalid log level: {value}. Must be one of {valid_levels}"
            raise ValueError(msg)
        return level_upper

    @field_validator("log_format")
    @classmethod
    def validate_log_format(cls, value: str) -> str:
        """Validate log format is one of the supported formats.

        Parameters
        ----------
        value : str
            Log format to validate.

        Returns
        -------
        str
            Validated log format (lowercase).

        Raises
        ------
        ValueError
            If log format is not supported.
        """
        valid_formats = {"json", "text"}
        format_lower = value.lower()
        if format_lower not in valid_formats:
            msg = f"Invalid log format: {value}. Must be one of {valid_formats}"
            raise ValueError(msg)
        return format_lower

    @field_validator("signing_key")
    @classmethod
    def validate_signing_key(cls, value: str | None) -> str | None:
        """Validate signing key is properly formatted and sufficiently long.

        Parameters
        ----------
        value : str | None
            Base64-encoded signing key.

        Returns
        -------
        str | None
            Validated signing key (unchanged if valid).

        Raises
        ------
        ValueError
            If key is invalid, not base64-decodable, or too short.
        """
        if value is None:
            return None

        if not value.strip():
            msg = "Signing key cannot be empty"
            raise ValueError(msg)

        try:
            decoded_key = base64.b64decode(value)
        except Exception as exc:
            msg = f"Signing key must be valid base64: {exc}"
            raise ValueError(msg) from exc

        if len(decoded_key) < _MIN_SIGNING_KEY_BYTES:
            msg = (
                f"Signing key must be ≥{_MIN_SIGNING_KEY_BYTES} bytes when decoded "
                f"(got {len(decoded_key)})"
            )
            raise ValueError(msg)

        return value

    @classmethod
    def from_dict(
        cls,
        values: Mapping[str, object] | None = None,
        *,
        context: Mapping[str, object] | None = None,
    ) -> Self:
        """Construct ``AppSettings`` from a mapping of overrides.

        This helper accepts a dictionary of configuration values—mirroring the
        structure provided by environment variables—and returns a fully validated
        ``AppSettings`` instance. It ensures keys are strings, preserves the
        original mapping order, and routes validation errors through the same
        normalization logic as ``model_validate`` so callers receive user-facing
        messages.

        Parameters
        ----------
        values : Mapping[str, object] | None, optional
            Mapping of configuration overrides. Keys must be strings that match
            the canonical field names used by ``AppSettings``. Defaults to an
            empty mapping when ``None`` is supplied.
        context : Mapping[str, object] | None, optional
            Optional Pydantic context forwarded to ``model_validate``.

        Returns
        -------
        Self
            Validated instance of AppSettings (same as Self).

        Raises
        ------
        TypeError
            If any key in ``values`` is not a string.

        Notes
        -----
        Propagates :class:`ValueError` from ``pydantic`` when validation fails;
        error messages mirror ``AppSettings`` field validators.
        """
        normalized: dict[str, object] = {}

        if values is not None:
            mapping_values = cast("Mapping[object, object]", values)
            for key_obj, value in mapping_values.items():
                if not isinstance(key_obj, str):
                    message = (
                        "AppSettings.from_dict requires string keys; "
                        f"received key of type {type(key_obj).__name__}"
                    )
                    raise TypeError(message)
                normalized[key_obj] = value

        return cls.model_validate(normalized, context=context)


def _load_config_impl() -> AppSettings:
    """Load and validate application configuration from environment.

    Returns
    -------
    AppSettings
        Validated application settings.

    Raises
    ------
    ValueError
        If configuration validation fails.
    """
    try:
        settings = AppSettings()
        logger.log_success(
            "Configuration loaded",
            operation="config.load",
            extra={
                "log_level": settings.log_level,
                "log_format": settings.log_format,
                "signing_key_present": settings.signing_key is not None,
                "subprocess_timeout": settings.subprocess_timeout,
                "request_timeout": settings.request_timeout,
            },
        )
    except ValueError as exc:
        logger.log_failure(
            "Configuration validation failed",
            exception=exc,
            operation="config.load",
        )
        raise
    else:
        return settings


_load_config_cached: functools._lru_cache_wrapper[AppSettings] = lru_cache(maxsize=1)(
    _load_config_impl
)


# [nav:anchor load_config]
def load_config(*, reload: bool = False) -> AppSettings:
    """Load application configuration from environment variables.

    This function caches the configuration to avoid repeated environment
    variable parsing. Pass reload=True to force a fresh load.

    Parameters
    ----------
    reload : bool, optional
        If True, clears the cache and reloads configuration from environment.
        Defaults to ``False``.

    Returns
    -------
    AppSettings
        Validated application settings.

    Notes
    -----
    Propagates :class:`ValueError` from ``pydantic`` when configuration
    validation fails (for example, due to an invalid log level).

    Examples
    --------
    >>> settings = load_config()
    >>> settings.log_level  # doctest: +SKIP
    'INFO'

    >>> # Reload configuration
    >>> settings = load_config(reload=True)  # doctest: +SKIP
    """
    if reload:
        _load_config_cached.cache_clear()

    return _load_config_cached()


def _format_validation_error(exc: ValidationError) -> str:
    """Return the most helpful message from a pydantic ``ValidationError``.

    Parameters
    ----------
    exc : ValidationError
        Validation error to format.

    Returns
    -------
    str
        Most helpful error message from the validation error.
    """
    errors_raw = cast("Sequence[Mapping[str, object]]", exc.errors())
    if errors_raw:
        primary = errors_raw[0]
        msg_obj = primary.get("msg")
        if isinstance(msg_obj, str) and msg_obj:
            return msg_obj
    return str(exc)
