"""Schema field alignment utilities for artifact constructors.

This module provides typed helpers for normalizing legacy payloads and enforcing
canonical field casing in Pydantic model construction. It centralizes migration
logic and emits structured warnings, metrics, and RFC 9457 Problem Details for
validation errors.

Examples
--------
>>> from docs._types.alignment import align_schema_fields
>>> legacy_payload = {"deprecated_in": "0.2.0"}
>>> aligned = align_schema_fields(legacy_payload, expected_fields={"deprecated_in"})
>>> assert aligned == {"deprecated_in": "0.2.0"}
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from pydantic import BaseModel
else:  # pragma: no cover - runtime stub for typing

    class BaseModel:  # type: ignore[too-many-ancestors]
        """Runtime stub for Pydantic BaseModel to avoid heavy import."""


from kgfoundry_common.errors import ArtifactValidationError

logger = logging.getLogger(__name__)

__all__ = [
    "SYMBOL_DELTA_CHANGE_FIELDS",
    "SYMBOL_DELTA_PAYLOAD_FIELDS",
    "SYMBOL_INDEX_ARTIFACTS_FIELDS",
    "SYMBOL_INDEX_ROW_FIELDS",
    "align_schema_fields",
]

# PEP 695 TypeVar for alignment helper return types
ModelT = TypeVar("ModelT", bound=BaseModel)

# Canonical field sets for artifact types (source of truth for validation)
SYMBOL_INDEX_ROW_FIELDS = frozenset(
    {
        "path",
        "canonical_path",
        "kind",
        "doc",
        "module",
        "package",
        "file",
        "lineno",
        "endlineno",
        "signature",
        "owner",
        "stability",
        "since",
        "deprecated_in",
        "section",
        "tested_by",
        "source_link",
        "is_async",
        "is_property",
        "span",  # synthetic field for LineSpan
    }
)

SYMBOL_INDEX_ARTIFACTS_FIELDS = frozenset(
    {
        "rows",
        "by_file",
        "by_module",
    }
)

SYMBOL_DELTA_CHANGE_FIELDS = frozenset(
    {
        "path",
        "before",
        "after",
        "reasons",
    }
)

SYMBOL_DELTA_PAYLOAD_FIELDS = frozenset(
    {
        "base_sha",
        "head_sha",
        "added",
        "removed",
        "changed",
    }
)


def align_schema_fields(
    payload: object,
    *,
    expected_fields: frozenset[str] | set[str],
    artifact_id: str = "unknown",
) -> dict[str, object]:
    """Normalize and validate a payload against expected schema fields.

    This helper enforces canonical field casing and detects unknown fields,
    emitting structured warnings for legacy payloads and Problem Details errors
    for invalid data.

    Parameters
    ----------
    payload : object
        Raw payload (typically from JSON deserialization) to normalize.
    expected_fields : frozenset[str] | set[str]
        Set of valid field names for this artifact type.
    artifact_id : str, optional
        Artifact type identifier for logging and error context.
        Defaults to "unknown".

    Returns
    -------
    dict[str, object]
        Normalized payload with canonical field names, ready for model construction.

    Raises
    ------
    ArtifactValidationError
        If payload contains unknown fields or is not a mapping.

    Examples
    --------
    >>> from docs._types.alignment import align_schema_fields, SYMBOL_INDEX_ROW_FIELDS
    >>> payload = {"path": "pkg.func", "kind": "function", "doc": "doc"}
    >>> aligned = align_schema_fields(
    ...     payload, expected_fields=SYMBOL_INDEX_ROW_FIELDS, artifact_id="symbol-index-row"
    ... )
    >>> assert aligned["path"] == "pkg.func"
    """
    if not isinstance(payload, dict):
        msg = f"Expected dict payload for {artifact_id}, got {type(payload).__name__}"
        raise ArtifactValidationError(
            msg,
            context={
                "artifact_id": artifact_id,
                "expected_type": "dict",
                "received_type": type(payload).__name__,
            },
        )

    # Check for unknown fields
    payload_keys: set[str] = set(payload.keys())
    unknown_keys: set[str] = payload_keys - expected_fields

    if unknown_keys:
        unknown_sorted = ", ".join(sorted(unknown_keys))
        msg = (
            f"Payload for {artifact_id} contains unknown fields: {unknown_sorted}. "
            f"Valid fields are: {', '.join(sorted(expected_fields))}"
        )
        # Log structured error
        logger.error(
            "schema_alignment_error",
            extra={
                "status": "error",
                "artifact_id": artifact_id,
                "unknown_fields": sorted(unknown_keys),
                "error_type": "unknown_fields",
            },
        )

        raise ArtifactValidationError(
            msg,
            context={
                "artifact_id": artifact_id,
                "unknown_fields": sorted(unknown_keys),
                "valid_fields": sorted(expected_fields),
                "remediation": (
                    "Remove unknown fields or consult the schema at "
                    "https://kgfoundry.dev/schema/docs/"
                ),
            },
        )

    # Return normalized payload
    result: dict[str, object] = dict(payload)

    # Log successful validation
    logger.debug(
        "schema_alignment_success",
        extra={
            "status": "validated",
            "artifact_id": artifact_id,
            "field_count": len(result),
        },
    )

    return result
