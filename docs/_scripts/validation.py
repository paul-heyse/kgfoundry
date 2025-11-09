"""Schema validation helpers for documentation tooling artifacts.

This module provides validation utilities for docs artifacts (symbol index, delta,
reverse lookups) against their canonical JSON Schema definitions. Validation failures
are surfaced as `ToolExecutionError` with RFC 9457 Problem Details payloads,
enabling structured error handling and observability hooks downstream.

The validator cache improves performance across multiple invocations by avoiding
repeated schema parsing and compilation.

Error Handling & Observability
-------------------------------
All validation failures raise `ToolExecutionError` with:
- Problem Details dict attached (`error.problem`) per RFC 9457
- Command tuple identifying the validation operation
- Optional stdout/stderr for diagnostic output
- Full exception chain preserved via `raise ... from`

Callers can log the `problem` field directly or render it to JSON for structured
error reporting. See `schema/examples/problem_details/docs-schema-validation.json`
for a canonical example.

Examples
--------
Typical usage in a docs build script::

    from docs._scripts.validation import validate_against_schema
    from pathlib import Path
    import json

    schema_path = Path("schema/docs/symbol-index.schema.json")
    payload = json.loads(Path("docs/_build/symbols.json").read_text())

    try:
        validate_against_schema(payload, schema_path, artifact="symbols.json")
    except ToolExecutionError as e:
        # Problem Details payload is ready for HTTP or CLI output
        print(json.dumps(e.problem, indent=2))
        raise
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, cast

from jsonschema import Draft202012Validator
from jsonschema import exceptions as jsonschema_exceptions
from tools._shared.problem_details import (
    ProblemDetailsParams,
    SchemaProblemDetailsParams,
    build_schema_problem_details,
)
from tools._shared.proc import ToolExecutionError

if TYPE_CHECKING:
    from pathlib import Path

    from tools._shared.problem_details import (
        ProblemDetailsDict,
    )

JsonPayload = Mapping[str, Any] | Sequence[Any] | str | int | float | bool | None

_VALIDATOR_CACHE: dict[Path, Draft202012Validator] = {}
_LOGGER = logging.getLogger(__name__)


def _get_validator(schema_path: Path) -> Draft202012Validator:
    """Load and cache a JSON Schema validator for the given schema file.

    Uses standard library json for deserialization with proper error handling.

    Parameters
    ----------
    schema_path : Path
        Path to the JSON Schema file.

    Returns
    -------
    Draft202012Validator
        Cached or newly created validator instance.

    Raises
    ------
    ValueError
        If the schema file cannot be read or parsed.
    """
    resolved = schema_path.resolve()
    cached = _VALIDATOR_CACHE.get(resolved)
    if cached is not None:
        return cached

    try:
        schema_text = resolved.read_text(encoding="utf-8")
        schema_data_raw: object = json.loads(schema_text)
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - I/O error
        _LOGGER.warning(
            "Failed to load JSON Schema from %s: %s",
            resolved,
            type(exc).__name__,
            extra={"status": "error", "path": str(resolved)},
        )
        message = f"Failed to load JSON Schema from {resolved}"
        raise ValueError(message) from exc

    schema_data = cast("dict[str, object]", schema_data_raw)
    Draft202012Validator.check_schema(schema_data)
    validator = Draft202012Validator(schema_data)
    _VALIDATOR_CACHE[resolved] = validator
    return validator


def _problem_for_validation(
    *,
    artifact: str,
    schema_path: Path,
    error: jsonschema_exceptions.ValidationError,
) -> ProblemDetailsDict:
    return build_schema_problem_details(
        SchemaProblemDetailsParams(
            base=ProblemDetailsParams(
                type="https://kgfoundry.dev/problems/docs-schema-validation",
                title="Docs artifact failed schema validation",
                status=422,
                detail="",
                instance=f"urn:docs:{artifact}:schema-validation",
            ),
            error=error,
            extensions={
                "artifact": artifact,
                "schema": str(schema_path),
            },
        )
    )


def validate_against_schema(
    payload: JsonPayload,
    schema_path: Path,
    *,
    artifact: str,
) -> None:
    """Validate a JSON-compatible ``payload`` against ``schema_path``.

    Parameters
    ----------
    payload : JsonPayload
        JSON-compatible payload to validate.
    schema_path : Path
        Absolute path to the JSON Schema file.
    artifact : str
        Artifact identifier used in problem details when validation fails.

    Raises
    ------
    ToolExecutionError
        When schema validation fails.
    """
    validator = _get_validator(schema_path)

    try:
        validator.validate(payload)
    except jsonschema_exceptions.ValidationError as exc:  # pragma: no cover - exercised in CLI
        problem = _problem_for_validation(artifact=artifact, schema_path=schema_path, error=exc)
        message = f"{artifact} failed schema validation"
        raise ToolExecutionError(
            message,
            command=["docs-schema-validate", artifact],
            problem=problem,
        ) from exc
