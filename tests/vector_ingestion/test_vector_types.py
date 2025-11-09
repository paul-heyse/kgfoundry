"""Unit tests for typed vector ingestion helpers.

These tests exercise ``kgfoundry_common.vector_types`` to ensure the shared
vector contract enforces dtype/shape invariants and raises
``VectorValidationError`` with informative messages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import numpy as np
import pytest

from kgfoundry_common.vector_types import (
    VectorBatch,
    VectorId,
    VectorValidationError,
    assert_vector_matrix,
    coerce_vector_batch,
    validate_vector_batch,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from kgfoundry_common.vector_types import (
        VectorMatrix,
    )


def test_coerce_vector_batch_produces_float32_matrix(
    canonical_vector_payload: list[dict[str, object]],
) -> None:
    """`coerce_vector_batch` converts payloads into contiguous float32 batches."""
    batch = coerce_vector_batch(canonical_vector_payload)

    assert batch.ids == (VectorId("vec-1"), VectorId("vec-2"))
    assert batch.count == 2
    assert batch.dimension == 3
    assert batch.matrix.dtype == np.float32
    assert batch.matrix.flags.c_contiguous


def test_coerce_vector_batch_rejects_inconsistent_dimensions(
    inconsistent_dimension_payload: list[dict[str, object]],
) -> None:
    """Ragged vectors should trigger a `VectorValidationError`."""
    with pytest.raises(VectorValidationError, match="differs from the expected dimension"):
        coerce_vector_batch(inconsistent_dimension_payload)


def test_coerce_vector_batch_rejects_non_numeric(
    non_numeric_payload: list[dict[str, object]],
) -> None:
    """Non-numeric vector entries bubble up as validation errors."""
    with pytest.raises(VectorValidationError, match="non-numeric vector entries"):
        coerce_vector_batch(non_numeric_payload)


def test_coerce_vector_batch_requires_mapping() -> None:
    """Vector records must be mapping objects with `key`/`vector` entries."""
    records: Iterable[object] = [[0.1, 0.2, 0.3]]

    with pytest.raises(VectorValidationError, match="Record 0 is missing a non-empty 'key' string"):
        coerce_vector_batch(cast("Iterable[Mapping[str, object]]", records))


def test_coerce_vector_batch_rejects_empty_or_duplicate_keys() -> None:
    """Empty datasets or duplicate ids should fail validation."""
    cases: Sequence[list[dict[str, object]]] = [
        [],
        [{"key": "", "vector": [0.1, 0.2]}],
        [
            {"key": "dup", "vector": [0.1, 0.2]},
            {"key": "dup", "vector": [0.1, 0.2]},
        ],
    ]

    for candidate in cases:
        with pytest.raises(VectorValidationError):
            coerce_vector_batch(candidate)


def test_assert_vector_matrix_accepts_float_lists() -> None:
    """`assert_vector_matrix` coerces nested sequences into contiguous float32 matrices."""
    matrix_input: Sequence[Sequence[float]] = ([1.0, 2.0], [3.0, 4.0])
    matrix = assert_vector_matrix(matrix_input)
    assert matrix.dtype == np.float32
    assert matrix.shape == (2, 2)
    assert matrix.flags.c_contiguous


def test_assert_vector_matrix_invalid_inputs() -> None:
    """Invalid matrices raise `VectorValidationError` with descriptive messages."""
    with pytest.raises(VectorValidationError, match="must be two-dimensional"):
        assert_vector_matrix([1.0, 2.0, 3.0])

    with pytest.raises(VectorValidationError, match="dimensionality must be greater than zero"):
        assert_vector_matrix(np.zeros((1, 0), dtype=np.float32))


def test_validate_vector_batch_returns_same_instance(
    canonical_vector_payload: list[dict[str, object]],
) -> None:
    """`validate_vector_batch` should not copy when invariants hold."""
    batch = coerce_vector_batch(canonical_vector_payload)
    validated = validate_vector_batch(batch)

    assert validated is batch


def test_validate_vector_batch_detects_mismatched_ids(
    canonical_vector_matrix: VectorMatrix,
) -> None:
    """Row count mismatches raise `VectorValidationError`."""
    ids = (VectorId("vec-1"),)
    batch = VectorBatch(ids=ids, matrix=canonical_vector_matrix)
    mismatched = VectorBatch(
        ids=(VectorId("vec-1"), VectorId("vec-1")), matrix=canonical_vector_matrix
    )

    with pytest.raises(VectorValidationError, match="row count"):
        validate_vector_batch(batch)

    with pytest.raises(VectorValidationError, match="unique"):
        validate_vector_batch(mismatched)


def test_vector_batch_dimension_and_count_properties(
    canonical_vector_payload: list[dict[str, object]],
) -> None:
    """`VectorBatch` exposes convenience properties for dimension and count."""
    batch = coerce_vector_batch(canonical_vector_payload)

    assert batch.count == 2
    assert batch.dimension == 3
