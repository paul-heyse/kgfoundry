"""Problem Details helpers for RFC 9457 compliance.

This module provides builders and helpers for creating RFC 9457 Problem Details
payloads used across tooling CLIs and error responses.

Examples
--------
>>> from tools._shared.problem_details import (
...     build_problem_details,
...     render_problem,
...     ProblemDetailsParams,
... )
>>> problem = build_problem_details(
...     ProblemDetailsParams(
...         type="https://kgfoundry.dev/problems/tool-failure",
...         title="Tool failed",
...         status=500,
...         detail="Command exited with code 1",
...         instance="urn:tool:git:exit-1",
...         extensions={"command": ["git", "status"], "returncode": 1},
...     )
... )
>>> json_str = render_problem(problem)
>>> assert "tool-failure" in json_str
"""

# pylint: disable=redefined-builtin

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__: tuple[str, ...] = (
    "ExceptionProblemDetailsParams",
    "JsonPrimitive",
    "JsonValue",
    "ProblemDetailsDict",
    "ProblemDetailsParams",
    "SchemaProblemDetailsParams",
    "ToolProblemDetailsParams",
    "build_problem_details",
    "build_schema_problem_details",
    "build_tool_problem_details",
    "coerce_optional_dict",
    "problem_from_exception",
    "render_problem",
    "tool_digest_mismatch_problem_details",
    "tool_disallowed_problem_details",
    "tool_failure_problem_details",
    "tool_missing_problem_details",
    "tool_timeout_problem_details",
)

# Type aliases for JSON values (RFC 7159 compatible)
JsonPrimitive = str | int | float | bool | None
JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]

ProblemDetailsDict = dict[str, JsonValue]


def coerce_optional_dict(
    mapping: Mapping[str, JsonValue] | None,
) -> dict[str, JsonValue] | None:
    """Return ``mapping`` as a ``dict`` when non-empty, otherwise ``None``.

    Parameters
    ----------
    mapping : Mapping[str, JsonValue] | None
        Mapping of extension values.

    Returns
    -------
    dict[str, JsonValue] | None
        Materialised dictionary or ``None`` when ``mapping`` is empty/``None``.
    """
    if mapping is None:
        return None
    materialised = {str(key): value for key, value in mapping.items()}
    if not materialised:
        return None
    return materialised


@dataclass(frozen=True, slots=True)
class ProblemDetailsParams:
    """Core fields required to build a Problem Details payload."""

    type: str
    title: str
    status: int
    detail: str
    instance: str
    extensions: Mapping[str, JsonValue] | None = None


def build_problem_details(params: ProblemDetailsParams) -> ProblemDetailsDict:
    """Build an RFC 9457 Problem Details payload.

    Parameters
    ----------
    params : ProblemDetailsParams
        Structured fields describing the Problem Details payload.

    Returns
    -------
    ProblemDetailsDict
        Problem Details payload conforming to RFC 9457.

    Examples
    --------
    >>> params = ProblemDetailsParams(
    ...     type="https://kgfoundry.dev/problems/tool-timeout",
    ...     title="Tool execution timed out",
    ...     status=504,
    ...     detail="Command 'git' timed out after 10.0 seconds",
    ...     instance="urn:tool:git:timeout",
    ...     extensions={"command": ["git", "status"], "timeout": 10.0},
    ... )
    >>> problem = build_problem_details(params)
    >>> assert problem["type"] == "https://kgfoundry.dev/problems/tool-timeout"
    >>> assert problem["status"] == 504
    """
    payload: ProblemDetailsDict = {
        "type": params.type,
        "title": params.title,
        "status": params.status,
        "detail": params.detail,
        "instance": params.instance,
    }
    extensions = coerce_optional_dict(params.extensions)
    if extensions:
        for key, value in extensions.items():
            payload[key] = value
    return payload


def _json_pointer_from(error: object) -> str | None:
    raw_path = getattr(error, "absolute_path", None)
    if isinstance(raw_path, Sequence):
        tokens = [str(part) for part in raw_path]
        if tokens:
            return "/" + "/".join(tokens)
    return None


@dataclass(frozen=True, slots=True)
class SchemaProblemDetailsParams:
    """Inputs required to construct schema validation problem details."""

    base: ProblemDetailsParams
    error: Exception
    extensions: Mapping[str, JsonValue] | None = None


def build_schema_problem_details(
    params: SchemaProblemDetailsParams,
) -> ProblemDetailsDict:
    """Return Problem Details payload describing a schema validation failure.

    Parameters
    ----------
    params : SchemaProblemDetailsParams
        Schema validation error context.

    Returns
    -------
    ProblemDetailsDict
        Problem Details payload.
    """
    detail_attr = getattr(params.error, "message", None)
    detail = str(detail_attr) if detail_attr is not None else str(params.error)
    extras: dict[str, JsonValue] = {}
    pointer = _json_pointer_from(params.error)
    if pointer:
        extras["jsonPointer"] = pointer
    validator_raw = getattr(params.error, "validator", None)
    if validator_raw is not None:
        extras["validator"] = str(validator_raw)
    additional = coerce_optional_dict(params.extensions)
    merged_extra: dict[str, JsonValue] | None = None
    if extras:
        merged_extra = dict(extras)
    if additional:
        if merged_extra is None:
            merged_extra = dict(additional)
        else:
            merged_extra.update(additional)
    base = replace(params.base, detail=detail, extensions=None)
    problem = build_problem_details(base)
    if merged_extra:
        problem["extensions"] = merged_extra
    return problem


@dataclass(frozen=True, slots=True)
class ToolProblemDetailsParams:
    """Inputs describing a tooling-related failure."""

    category: str
    command: Sequence[str]
    status: int
    title: str
    detail: str
    instance_suffix: str
    extensions: Mapping[str, JsonValue] | None = None


def build_tool_problem_details(params: ToolProblemDetailsParams) -> ProblemDetailsDict:
    """Return a Problem Details payload describing a tooling subprocess failure.

    Parameters
    ----------
    params : ToolProblemDetailsParams
        Tool execution failure context.

    Returns
    -------
    ProblemDetailsDict
        Problem Details payload.
    """
    command_list = list(params.command)
    tool_name = Path(command_list[0]).name if command_list else "<unknown>"
    command_extension: JsonValue = [str(part) for part in command_list]
    merged_extensions: dict[str, JsonValue] = {"command": command_extension}
    additional_extensions = coerce_optional_dict(params.extensions)
    if additional_extensions:
        merged_extensions.update(additional_extensions)
    base = ProblemDetailsParams(
        type=f"https://kgfoundry.dev/problems/{params.category}",
        title=params.title,
        status=params.status,
        detail=params.detail,
        instance=f"urn:tool:{tool_name}:{params.instance_suffix}",
        extensions=merged_extensions,
    )
    return build_problem_details(base)


def tool_timeout_problem_details(
    command: Sequence[str],
    *,
    timeout: float | None,
) -> ProblemDetailsDict:
    """Return Problem Details describing a tooling timeout.

    Parameters
    ----------
    command : Sequence[str]
        Command that timed out.
    timeout : float | None
        Timeout duration in seconds.

    Returns
    -------
    ProblemDetailsDict
        Problem Details payload.
    """
    detail = (
        f"Command '{command[0]}' timed out after {timeout} seconds"
        if command and timeout is not None
        else (f"Command '{command[0]}' timed out" if command else "Command timed out")
    )
    extensions: dict[str, JsonValue] = {}
    if timeout is not None:
        extensions["timeout"] = timeout
    return build_tool_problem_details(
        ToolProblemDetailsParams(
            category="tool-timeout",
            command=command,
            status=504,
            title="Tool execution timed out",
            detail=detail,
            instance_suffix="timeout",
            extensions=coerce_optional_dict(extensions),
        )
    )


def tool_missing_problem_details(
    command: Sequence[str],
    *,
    executable: str,
    detail: str,
) -> ProblemDetailsDict:
    """Return Problem Details describing a missing executable.

    Parameters
    ----------
    command : Sequence[str]
        Command that failed.
    executable : str
        Executable name that was not found.
    detail : str
        Detailed error message.

    Returns
    -------
    ProblemDetailsDict
        Problem Details payload.
    """
    return build_tool_problem_details(
        ToolProblemDetailsParams(
            category="tool-missing",
            command=command or [executable],
            status=500,
            title="Executable not found",
            detail=detail,
            instance_suffix="missing",
        )
    )


def tool_disallowed_problem_details(
    command: Sequence[str],
    *,
    executable: Path,
    allowlist: Sequence[str],
) -> ProblemDetailsDict:
    """Return Problem Details describing an allowlisted executable violation.

    Parameters
    ----------
    command : Sequence[str]
        Command that was rejected.
    executable : Path
        Executable path that violated the allowlist.
    allowlist : Sequence[str]
        Configured allowlist patterns.

    Returns
    -------
    ProblemDetailsDict
        Problem Details payload.
    """
    return build_tool_problem_details(
        ToolProblemDetailsParams(
            category="tool-exec-disallowed",
            command=command,
            status=403,
            title="Executable not allowed",
            detail=(
                f"Executable '{executable.name}' is not permitted by the TOOLS_EXEC_ALLOWLIST setting"
            ),
            instance_suffix="disallowed",
            extensions={
                "executable": str(executable),
                "allowlist": list(allowlist),
            },
        )
    )


def tool_digest_mismatch_problem_details(
    command: Sequence[str],
    *,
    executable: Path,
    expected_digest: str,
    actual_digest: str | None,
    reason: str,
) -> ProblemDetailsDict:
    """Return Problem Details describing an executable digest verification failure.

    Parameters
    ----------
    command : Sequence[str]
        Command that failed verification.
    executable : Path
        Executable path.
    expected_digest : str
        Expected SHA256 digest.
    actual_digest : str | None
        Actual digest if available.
    reason : str
        Failure reason.

    Returns
    -------
    ProblemDetailsDict
        Problem Details payload.
    """
    extensions: dict[str, JsonValue] = {
        "executable": str(executable),
        "expectedDigest": expected_digest,
        "reason": reason,
    }
    if actual_digest is not None:
        extensions["actualDigest"] = actual_digest
    return build_tool_problem_details(
        ToolProblemDetailsParams(
            category="tool-exec-digest-mismatch",
            command=command,
            status=403,
            title="Executable digest verification failed",
            detail=(
                "Executable digest does not match the expected value configured in TOOLS_EXEC_DIGESTS"
            ),
            instance_suffix="digest-mismatch",
            extensions=extensions,
        )
    )


def tool_failure_problem_details(
    command: Sequence[str],
    *,
    returncode: int,
    detail: str,
) -> ProblemDetailsDict:
    """Return Problem Details describing a non-zero tooling exit code.

    Parameters
    ----------
    command : Sequence[str]
        Command that failed.
    returncode : int
        Non-zero exit code.
    detail : str
        Detailed error message.

    Returns
    -------
    ProblemDetailsDict
        Problem Details payload.
    """
    return build_tool_problem_details(
        ToolProblemDetailsParams(
            category="tool-failure",
            command=command,
            status=500,
            title="Tool returned a non-zero exit code",
            detail=detail,
            instance_suffix=f"exit-{returncode}",
            extensions={"returncode": returncode},
        )
    )


@dataclass(frozen=True, slots=True)
class ExceptionProblemDetailsParams:
    """Inputs describing a generic exception converted to Problem Details."""

    base: ProblemDetailsParams
    exception: Exception
    extensions: Mapping[str, JsonValue] | None = None


def problem_from_exception(params: ExceptionProblemDetailsParams) -> ProblemDetailsDict:
    """Build Problem Details from an exception.

    Parameters
    ----------
    params : ExceptionProblemDetailsParams
        Structured context describing the exception and base problem fields.

    Returns
    -------
    ProblemDetailsDict
        Problem Details payload.

    Examples
    --------
    >>> try:
    ...     raise ValueError("Invalid input")
    ... except ValueError as exc:
    ...     problem = problem_from_exception(
    ...         ExceptionProblemDetailsParams(
    ...             base=ProblemDetailsParams(
    ...                 type="https://kgfoundry.dev/problems/invalid-input",
    ...                 title="Invalid input",
    ...                 status=400,
    ...                 detail="",
    ...                 instance="urn:validation:input",
    ...             ),
    ...             exception=exc,
    ...         )
    ...     )
    >>> assert "Invalid input" in problem["detail"]
    """
    detail = str(params.exception)
    exc_type_name = params.exception.__class__.__name__
    merged_extensions: dict[str, JsonValue] = {"exception_type": exc_type_name}
    if params.extensions:
        merged_extensions.update(params.extensions)
    base = replace(params.base, detail=detail, extensions=merged_extensions)
    return build_problem_details(base)


def render_problem(problem: ProblemDetailsDict) -> str:
    """Render Problem Details as JSON string.

    This function serializes a Problem Details payload to JSON for stdout
    or HTTP response bodies.

    Parameters
    ----------
    problem : ProblemDetailsDict
        Problem Details payload.

    Returns
    -------
    str
        JSON-encoded Problem Details (minified, no trailing newline).

    Examples
    --------
    >>> problem = build_problem_details(
    ...     ProblemDetailsParams(
    ...         type="https://kgfoundry.dev/problems/tool-failure",
    ...         title="Tool failed",
    ...         status=500,
    ...         detail="Command failed",
    ...         instance="urn:tool:git:exit-1",
    ...     )
    ... )
    >>> json_str = render_problem(problem)
    >>> assert json_str.startswith("{")
    >>> assert "tool-failure" in json_str
    """
    return json.dumps(problem, default=str)
