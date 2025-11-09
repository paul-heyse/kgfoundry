"""Shared fixtures for vector ingestion regression tests.

These fixtures provide canonical payloads, schema validators, and deterministic correlation
identifiers so the test suite can exercise vector ingestion behaviour without repeating setup
boilerplate.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final, cast
from uuid import UUID

import numpy as np
import pytest

from kgfoundry_common.jsonschema_utils import (
    create_draft202012_validator,
)
from kgfoundry_common.schema_helpers import load_schema

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from kgfoundry_common.jsonschema_utils import (
        Draft202012ValidatorProtocol,
    )
    from kgfoundry_common.types import JsonValue
    from kgfoundry_common.vector_types import VectorMatrix

type VectorPayload = list[dict[str, object]]

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_VECTOR_SCHEMA_PATH: Final[Path] = (
    _REPO_ROOT / "schema" / "vector-ingestion" / "vector-batch.v1.schema.json"
)


def _vector_schema_path() -> Path:
    """Return the absolute path to the canonical vector batch schema.

    Returns
    -------
    Path
        Path to vector batch schema file.
    """
    return _VECTOR_SCHEMA_PATH


vector_schema_path: Callable[[], Path] = pytest.fixture(scope="session")(
    _vector_schema_path
)


def _vector_schema(vector_schema_path: Path) -> dict[str, JsonValue]:
    """Load the canonical vector batch schema once per test session.

    Parameters
    ----------
    vector_schema_path : Path
        Path to schema file.

    Returns
    -------
    dict[str, JsonValue]
        Parsed schema dictionary.
    """
    return load_schema(vector_schema_path)


vector_schema: Callable[[Path], dict[str, JsonValue]] = pytest.fixture(scope="session")(
    _vector_schema
)


def _vector_validator(
    vector_schema: dict[str, JsonValue],
) -> Draft202012ValidatorProtocol:
    """Provide a cached JSON Schema validator for vector payloads.

    Parameters
    ----------
    vector_schema : dict[str, JsonValue]
        Schema dictionary.

    Returns
    -------
    Draft202012ValidatorProtocol
        Validator instance.
    """
    return create_draft202012_validator(vector_schema)


vector_validator: Callable[[dict[str, JsonValue]], Draft202012ValidatorProtocol] = (
    pytest.fixture(scope="session")(_vector_validator)
)


def _canonical_vector_payload() -> VectorPayload:
    """Return a well-formed vector payload used across tests.

    Returns
    -------
    VectorPayload
        List of vector records.
    """
    return [
        {"key": "vec-1", "vector": [0.1, 0.2, 0.3]},
        {"key": "vec-2", "vector": [0.4, 0.5, 0.6]},
    ]


canonical_vector_payload: Callable[[], VectorPayload] = pytest.fixture(
    _canonical_vector_payload
)


def _inconsistent_dimension_payload() -> VectorPayload:
    """Return a payload containing a ragged vector for negative tests.

    Returns
    -------
    VectorPayload
        Payload with inconsistent vector dimensions.
    """
    return [
        {"key": "vec-1", "vector": [0.1, 0.2, 0.3]},
        {"key": "vec-2", "vector": [0.4, 0.5]},
    ]


inconsistent_dimension_payload: Callable[[], VectorPayload] = pytest.fixture(
    _inconsistent_dimension_payload
)


def _non_numeric_payload() -> VectorPayload:
    """Return a payload with non-numeric entries for validation failures.

    Returns
    -------
    VectorPayload
        Payload with invalid numeric values.
    """
    return [
        {"key": "vec-1", "vector": [0.1, "oops", 0.3]},
    ]


non_numeric_payload: Callable[[], VectorPayload] = pytest.fixture(_non_numeric_payload)


def _canonical_vector_matrix(canonical_vector_payload: VectorPayload) -> VectorMatrix:
    """Return a numpy matrix representation of the canonical payload.

    Parameters
    ----------
    canonical_vector_payload : VectorPayload
        Vector payload to convert.

    Returns
    -------
    VectorMatrix
        NumPy array matrix representation.
    """
    vectors = [
        cast("Sequence[float]", record["vector"]) for record in canonical_vector_payload
    ]
    return np.asarray(vectors, dtype=np.float32)


canonical_vector_matrix: Callable[[VectorPayload], VectorMatrix] = pytest.fixture(
    _canonical_vector_matrix
)


_DETERMINISTIC_UUID: Final[UUID] = UUID("12345678-1234-5678-1234-567812345678")


def _deterministic_uuid() -> UUID:
    """Return a deterministic UUID for correlation ID tests.

    Returns
    -------
    UUID
        Fixed UUID value.
    """
    return _DETERMINISTIC_UUID


deterministic_uuid: Callable[[], UUID] = pytest.fixture(_deterministic_uuid)


def _correlation_id_hex(deterministic_uuid: UUID) -> str:
    """Expose the hexadecimal correlation identifier used in tests.

    Parameters
    ----------
    deterministic_uuid : UUID
        UUID to convert.

    Returns
    -------
    str
        Hexadecimal string representation.
    """
    return deterministic_uuid.hex


correlation_id_hex: Callable[[UUID], str] = pytest.fixture(_correlation_id_hex)


def _deterministic_uuid_factory(deterministic_uuid: UUID) -> Callable[[], UUID]:
    """Return a callable that mimics :func:`uuid.uuid4` deterministically.

    Parameters
    ----------
    deterministic_uuid : UUID
        UUID to return.

    Returns
    -------
    Callable[[], UUID]
        Factory function returning the deterministic UUID.
    """

    def _factory() -> UUID:
        return deterministic_uuid

    return _factory


deterministic_uuid_factory: Callable[[UUID], Callable[[], UUID]] = pytest.fixture(
    _deterministic_uuid_factory
)
