"""RFC 9457 Problem Details helpers with schema validation.

This module provides typed helpers for building RFC 9457 Problem Details payloads
with JSON Schema 2020-12 validation. All payloads validate against the canonical
schema at `schema/common/problem_details.json`.

Examples
--------
>>> from kgfoundry_common.problem_details import build_problem_details, render_problem
>>> problem = build_problem_details(
...     type="https://kgfoundry.dev/problems/tool-failure",
...     title="Tool failed",
...     status=500,
...     detail="Command exited with code 1",
...     instance="urn:tool:git:exit-1",
...     extensions={"command": ["git", "status"], "returncode": 1},
... )
>>> json_str = render_problem(problem)
>>> assert "tool-failure" in json_str
"""

# [nav:section public-api]

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, TypedDict, cast, overload

from kgfoundry_common.fs import read_text
from kgfoundry_common.jsonschema_utils import (
    Draft202012Validator,
    SchemaError,
    ValidationError,
)
from kgfoundry_common.jsonschema_utils import (
    validate as jsonschema_validate,
)
from kgfoundry_common.logging import get_logger
from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.types import JsonPrimitive, JsonValue

if TYPE_CHECKING:
    from collections.abc import Mapping

    from kgfoundry_common.jsonschema_utils import (
        ValidationErrorProtocol,
    )

# [nav:anchor JsonObject]
JsonObject = dict[str, JsonValue]
# [nav:anchor ProblemDetailsDict]
ProblemDetailsDict = dict[str, JsonValue]

# JSON Schema type for cached schema objects
JsonSchema = dict[str, object]


__all__ = [
    "ExceptionProblemDetailsParams",
    "JsonObject",
    "JsonPrimitive",
    "JsonValue",
    "ProblemDetails",
    "ProblemDetailsDict",
    "ProblemDetailsParams",
    "ProblemDetailsValidationError",
    "build_configuration_problem",
    "build_problem_details",
    "problem_from_exception",
    "render_problem",
    "validate_problem_details",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))
logger = get_logger(__name__)

# Path to canonical Problem Details schema
_SCHEMA_PATH = Path(__file__).parent.parent.parent / "schema" / "common" / "problem_details.json"


# [nav:anchor ProblemDetails]
class ProblemDetails(TypedDict, total=False):
    """TypedDict for RFC 9457 Problem Details responses.

    This is a partial TypedDict (total=False) where all fields are optional, allowing for flexible
    payload construction with validation.
    """

    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str  # NotRequired via total=False
    extensions: dict[str, JsonValue]  # NotRequired via total=False


@dataclass(slots=True, frozen=True)
# [nav:anchor ProblemDetailsParams]
class ProblemDetailsParams:
    """Parameters used to construct a Problem Details payload."""

    problem_type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str | None = None
    extensions: Mapping[str, JsonValue] | None = None


@dataclass(slots=True, frozen=True)
# [nav:anchor ExceptionProblemDetailsParams]
class ExceptionProblemDetailsParams:
    """Parameters describing an exception converted to Problem Details."""

    exception: Exception
    base: ProblemDetailsParams


# [nav:anchor ProblemDetailsValidationError]
class ProblemDetailsValidationError(Exception):
    """Raised when Problem Details payload fails schema validation.

    This exception is raised when a Problem Details dictionary does not conform
    to the RFC 9457 schema or fails validation against the canonical JSON Schema.

    Initializes the validation error with message and optional validation error details.

    Parameters
    ----------
    message : str
        Human-readable error message describing the validation failure.
    validation_errors : list[str] | None, optional
        List of specific validation error messages from the schema validator.
        Provides detailed path and constraint information. Defaults to None.

    Examples
    --------
    >>> raise ProblemDetailsValidationError("Missing required field: type")
    Traceback (most recent call last):
        ...
    ProblemDetailsValidationError: Missing required field: type
    """

    def __init__(self, message: str, validation_errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.validation_errors = validation_errors or []


_SCHEMA_CACHE: dict[str, JsonSchema] = {}


def _load_schema_impl() -> JsonSchema:
    """Load and parse the Problem Details schema from disk.

    Loads the canonical RFC 9457 Problem Details schema file, validates it
    against the JSON Schema 2020-12 meta-schema, and returns the parsed
    dictionary.

    Returns
    -------
    JsonSchema
        Parsed schema dictionary conforming to JSON Schema 2020-12.

    Raises
    ------
    ProblemDetailsValidationError
        If schema file is missing, invalid JSON, or fails meta-schema
        validation.
    """
    if not _SCHEMA_PATH.exists():
        msg = f"Problem Details schema not found: {_SCHEMA_PATH}"
        raise ProblemDetailsValidationError(msg)

    try:
        schema_text = read_text(_SCHEMA_PATH)
        schema_obj: dict[str, object] = json.loads(schema_text)
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"Failed to load Problem Details schema: {exc}"
        raise ProblemDetailsValidationError(msg) from exc

    # Validate against JSON Schema 2020-12 meta-schema
    try:
        Draft202012Validator.check_schema(schema_obj)
    except SchemaError as exc:
        msg = f"Invalid Problem Details schema: {exc}"
        raise ProblemDetailsValidationError(msg) from exc

    return schema_obj


def _load_schema() -> JsonSchema:
    """Return the cached Problem Details JSON Schema.

    Returns
    -------
    JsonSchema
        Cached JSON Schema for Problem Details.
    """
    cached = _SCHEMA_CACHE.get("problem_details")
    if cached is not None:
        return cached

    schema = _load_schema_impl()
    _SCHEMA_CACHE["problem_details"] = schema
    return schema


# [nav:anchor validate_problem_details]
def validate_problem_details(payload: Mapping[str, JsonValue]) -> None:
    """Validate Problem Details payload against canonical schema.

    Validates a Problem Details dictionary against the RFC 9457 schema
    (JSON Schema 2020-12). Raises an exception if validation fails with
    detailed error information including the JSON path where validation
    failed.

    Parameters
    ----------
    payload : Mapping[str, JsonValue]
        Problem Details payload to validate. Must conform to RFC 9457
        structure with required fields: type, title, status, detail, instance.

    Raises
    ------
    ProblemDetailsValidationError
        If payload fails schema validation. The exception includes
        validation_errors list with specific constraint violations.

    Examples
    --------
    >>> problem = {
    ...     "type": "https://kgfoundry.dev/problems/runtime-error",
    ...     "title": "Runtime Error",
    ...     "status": 500,
    ...     "detail": "Operation failed",
    ...     "instance": "/api/v1/operation",
    ... }
    >>> validate_problem_details(problem)
    """
    schema = _load_schema()
    try:
        jsonschema_validate(instance=payload, schema=schema)
    except ValidationError as exc:
        error_details = cast("ValidationErrorProtocol", exc)
        errors = [error_details.message]
        if error_details.absolute_path:
            path_str = ".".join(str(p) for p in error_details.absolute_path)
            errors.append(f"at path: {path_str}")
        msg = f"Problem Details validation failed: {'; '.join(errors)}"
        raise ProblemDetailsValidationError(msg, validation_errors=errors) from exc
    except SchemaError as exc:
        msg = f"Invalid schema: {exc}"
        raise ProblemDetailsValidationError(msg) from exc


def _type_error(message: str) -> NoReturn:
    raise TypeError(message)


def _ensure_int(value: object, *, message: str) -> int:
    if isinstance(value, int):
        return value
    _type_error(message)


def _ensure_exception(value: object, *, message: str) -> Exception:
    if isinstance(value, Exception):
        return value
    _type_error(message)


def _first_arg(args: tuple[object, ...], *, func_name: str) -> object:
    if len(args) == 0:
        _type_error(f"{func_name}() missing required argument")
    return args[0]


def _coerce_problem_details_params(*args: object, **kwargs: object) -> ProblemDetailsParams:
    if len(args) > 0 and isinstance(args[0], ProblemDetailsParams):
        if len(args) > 1 or kwargs:
            _type_error("build_problem_details() received unexpected extra arguments")
        return args[0]

    positional = ("problem_type", "title", "status", "detail", "instance")
    if len(args) > len(positional):
        _type_error("build_problem_details() received too many positional arguments")

    values: dict[str, object] = dict(zip(positional, args, strict=False))

    remaining_fields = positional[len(args) :]
    missing_fields = [field_name for field_name in remaining_fields if field_name not in kwargs]
    if missing_fields:
        missing = missing_fields[0]
        _type_error(f"build_problem_details() missing required argument: '{missing}'")
    values.update({field_name: kwargs.pop(field_name) for field_name in remaining_fields})

    code = kwargs.pop("code", None)
    extensions = kwargs.pop("extensions", None)
    if kwargs:
        unexpected = ", ".join(sorted(kwargs))
        _type_error(f"build_problem_details() got unexpected keyword arguments: {unexpected}")

    status_int = _ensure_int(
        values["status"],
        message="build_problem_details() expected 'status' to be an int",
    )

    return ProblemDetailsParams(
        problem_type=str(values["problem_type"]),
        title=str(values["title"]),
        status=status_int,
        detail=str(values["detail"]),
        instance=str(values["instance"]),
        code=None if code is None else str(code),
        extensions=cast("Mapping[str, JsonValue] | None", extensions),
    )


def _coerce_exception_params(*args: object, **kwargs: object) -> ExceptionProblemDetailsParams:
    if len(args) > 0 and isinstance(args[0], ExceptionProblemDetailsParams):
        if len(args) > 1 or kwargs:
            _type_error("problem_from_exception() received unexpected extra arguments")
        return args[0]

    if len(args) == 0:
        _type_error("problem_from_exception() missing required argument: 'exc'")

    first_arg = _first_arg(args, func_name="problem_from_exception")
    exc = _ensure_exception(
        first_arg,
        message="problem_from_exception() first argument must be an Exception instance",
    )

    if "detail" in kwargs:
        _type_error("problem_from_exception() does not accept a 'detail' argument")

    base_args = args[1:]
    combined_kwargs = dict(kwargs)
    combined_kwargs["detail"] = str(exc)

    base_params = _coerce_problem_details_params(*base_args, **combined_kwargs)
    return ExceptionProblemDetailsParams(exception=exc, base=base_params)


@overload
def build_problem_details(params: ProblemDetailsParams, /) -> ProblemDetails: ...


@overload
def build_problem_details(
    problem_type: str,
    title: str,
    status: int,
    detail: str,
    instance: str,
    *,
    code: str | None = ...,
    extensions: Mapping[str, JsonValue] | None = ...,
) -> ProblemDetails: ...


# [nav:anchor build_problem_details]
def build_problem_details(*args: object, **kwargs: object) -> ProblemDetails:
    """Build an RFC 9457 Problem Details payload.

    Constructs a Problem Details dictionary conforming to RFC 9457 and
    validates it against the canonical schema. Supports both dataclass
    and positional/keyword argument calling styles.

    Parameters
    ----------
    *args : object
        Either a single :class:`ProblemDetailsParams` instance or the
        positional fields ``(problem_type, title, status, detail, instance)``
        in that order.
    **kwargs : object
        Optional keyword arguments accepted when the dataclass form is not
        used. Supports ``code`` and ``extensions`` for the legacy calling
        style.

    Returns
    -------
    ProblemDetails
        Problem Details payload conforming to RFC 9457 and validated against
        schema. Contains required fields: type, title, status, detail, instance.
        May include optional fields: code, extensions.

    Notes
    -----
    The function performs runtime type coercion and validation before
    constructing the payload. Schema validation errors raised by
    :func:`validate_problem_details` propagate unchanged.

    Examples
    --------
    >>> problem = build_problem_details(
    ...     problem_type="https://kgfoundry.dev/problems/tool-timeout",
    ...     title="Tool execution timed out",
    ...     status=504,
    ...     detail="Command 'git' timed out after 10.0 seconds",
    ...     instance="urn:tool:git:timeout",
    ...     extensions={"command": ["git", "status"], "timeout": 10.0},
    ... )
    >>> assert problem["type"] == "https://kgfoundry.dev/problems/tool-timeout"
    >>> assert problem["status"] == 504
    """
    params = _coerce_problem_details_params(*args, **kwargs)
    payload: dict[str, object] = {
        "type": params.problem_type,
        "title": params.title,
        "status": params.status,
        "detail": params.detail,
        "instance": params.instance,
    }
    if params.code is not None:
        payload["code"] = params.code
    if params.extensions:
        payload["extensions"] = dict(params.extensions)

    # Validate against schema (cast since dict[str, object] ⊇ Mapping[str, JsonValue])
    validate_problem_details(cast("Mapping[str, JsonValue]", payload))

    return cast("ProblemDetails", payload)


@overload
def problem_from_exception(params: ExceptionProblemDetailsParams) -> ProblemDetails: ...


@overload
def problem_from_exception(
    exc: Exception,
    problem_type: str,
    title: str,
    status: int,
    instance: str,
    *,
    code: str | None = ...,
    extensions: Mapping[str, JsonValue] | None = ...,
) -> ProblemDetails: ...


# [nav:anchor problem_from_exception]
def problem_from_exception(*args: object, **kwargs: object) -> ProblemDetails:
    """Build Problem Details from an exception.

    Constructs a Problem Details payload from an exception instance,
    extracting the exception message as the detail field and automatically
    including exception type and cause chain information in extensions.

    Parameters
    ----------
    *args : object
        Either a single :class:`ExceptionProblemDetailsParams` instance or
        the legacy positional arguments ``(exc, problem_type, title, status,
        instance)``.
    **kwargs : object
        Optional keyword arguments accepted when the dataclass form is not used.
        Supports ``code`` and ``extensions`` for backward compatibility. Note
        that ``detail`` cannot be provided as a keyword argument; it is
        automatically extracted from the exception.

    Returns
    -------
    ProblemDetails
        Problem Details payload with detail field set to the exception's
        string representation. Extensions include ``exception_type`` and
        optionally ``caused_by`` if the exception has a cause chain.

    Notes
    -----
    The exception's string representation (via ``str(exc)``) is used as the
    detail field. The exception type name is added to extensions. If the
    exception has a ``__cause__`` attribute, it is included in extensions as
    ``caused_by``. Schema validation errors raised by
    :func:`validate_problem_details` propagate unchanged.

    Examples
    --------
    >>> try:
    ...     raise ValueError("Invalid input")
    ... except ValueError as e:
    ...     problem = problem_from_exception(
    ...         e,
    ...         problem_type="https://kgfoundry.dev/problems/invalid-input",
    ...         title="Invalid input",
    ...         status=400,
    ...         instance="urn:validation:input",
    ...     )
    >>> assert "Invalid input" in problem["detail"]
    >>> assert problem["extensions"]["exception_type"] == "ValueError"
    """
    params = _coerce_exception_params(*args, **kwargs)
    exc = params.exception
    detail = params.base.detail
    exc_type_name = exc.__class__.__name__
    merged_extensions: dict[str, JsonValue] = {
        "exception_type": exc_type_name,
    }
    if params.base.extensions:
        merged_extensions.update(dict(params.base.extensions))

    # Preserve cause chain if present
    if exc.__cause__ is not None:
        merged_extensions["caused_by"] = exc.__cause__.__class__.__name__

    return build_problem_details(
        ProblemDetailsParams(
            problem_type=params.base.problem_type,
            title=params.base.title,
            status=params.base.status,
            detail=detail,
            instance=params.base.instance,
            code=params.base.code,
            extensions=merged_extensions,
        )
    )


# [nav:anchor build_configuration_problem]
def build_configuration_problem(
    config_error: Exception,
) -> ProblemDetails:
    """Build Problem Details from a ConfigurationError.

    Parameters
    ----------
    config_error : Exception
        A ConfigurationError instance with validation context.

    Returns
    -------
    ProblemDetails
        Problem Details payload with configuration error details.

    Raises
    ------
    TypeError
        If the provided exception is not a ConfigurationError.

    Examples
    --------
    >>> from kgfoundry_common.errors import ConfigurationError
    >>> error = ConfigurationError.with_details(
    ...     field="api_key",
    ...     issue="Missing required environment variable",
    ...     hint="Set KGFOUNDRY_API_KEY before running",
    ... )
    >>> problem = build_configuration_problem(error)
    >>> assert problem["status"] == 500
    >>> assert "api_key" in str(problem["extensions"])
    """
    # Check class name to avoid circular import
    if type(config_error).__name__ != "ConfigurationError":
        msg = (
            "build_configuration_problem() expected ConfigurationError, "
            f"got {type(config_error).__name__}"
        )
        raise TypeError(msg)

    # Verify it has the expected attributes
    if not hasattr(config_error, "message") or not hasattr(config_error, "http_status"):
        msg = (
            "build_configuration_problem() expected object with 'message' "
            "and 'http_status' attributes"
        )
        raise TypeError(msg)

    # Extract field details from context if available
    extensions: dict[str, JsonValue] = {
        "exception_type": "ConfigurationError",
    }
    context_value: object = getattr(config_error, "context", None)
    if isinstance(context_value, dict):
        extensions["validation"] = cast("dict[str, JsonValue]", context_value)

    # Get the message - use str() as fallback
    msg_value: object = getattr(config_error, "message", None)
    message: str = msg_value if isinstance(msg_value, str) else str(config_error)

    # Get http_status - expect int, default to 500
    http_attr: object = getattr(config_error, "http_status", 500)
    http_status: int = http_attr if isinstance(http_attr, int) else 500

    # Get code value - should be ErrorCode enum with .value attribute
    code_obj: object = getattr(config_error, "code", None)
    value_attr: object = getattr(code_obj, "value", None)
    code_value: str = value_attr if isinstance(value_attr, str) else "configuration-error"

    return build_problem_details(
        problem_type="https://kgfoundry.dev/problems/configuration-error",
        title="Configuration Error",
        status=http_status,
        detail=message,
        instance="urn:config:validation",
        code=code_value,
        extensions=extensions,
    )


# [nav:anchor render_problem]
def render_problem(problem: ProblemDetails | dict[str, object]) -> str:
    """Render Problem Details as JSON string.

    Serializes a Problem Details payload to a JSON string suitable for
    stdout output or HTTP response bodies. The output is minified (no
    indentation) and does not include a trailing newline.

    Parameters
    ----------
    problem : ProblemDetails | dict[str, object]
        Problem Details payload to serialize. Must be JSON-serializable.

    Returns
    -------
    str
        JSON-encoded Problem Details string (minified, no trailing newline).
        Uses UTF-8 encoding and preserves non-ASCII characters.

    Examples
    --------
    >>> problem = build_problem_details(
    ...     problem_type="https://kgfoundry.dev/problems/tool-failure",
    ...     title="Tool failed",
    ...     status=500,
    ...     detail="Command failed",
    ...     instance="urn:tool:git:exit-1",
    ... )
    >>> json_str = render_problem(problem)
    >>> assert json_str.startswith("{")
    >>> assert "tool-failure" in json_str
    """
    return json.dumps(problem, default=str, ensure_ascii=False)
