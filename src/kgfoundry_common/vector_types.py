"""Typed vector contracts and validation helpers for vector ingestion.

This module centralises numpy vector typing so callers can construct and validate
vector batches without leaking ``Any`` through numpy operations. All helpers
return ``float32`` matrices and raise :class:`VectorValidationError` with rich
context when inputs are malformed.

Examples
--------
>>> from kgfoundry_common.vector_types import coerce_vector_batch
>>> payload = [
...     {"key": "doc-1", "vector": [0.1, 0.2, 0.3]},
...     {"key": "doc-2", "vector": [0.4, 0.5, 0.6]},
... ]
>>> batch = coerce_vector_batch(payload)
>>> batch.ids
(VectorId('doc-1'), VectorId('doc-2'))
>>> batch.matrix.dtype
dtype('float32')
>>> batch.matrix.shape
(2, 3)
"""

# [nav:section public-api]

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, NewType, cast

from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.typing import gate_import

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable, Sequence

    import numpy as np
    import numpy.typing as npt

    type VectorMatrix = npt.NDArray[np.float32]
else:  # pragma: no cover - runtime fallback
    np = gate_import("numpy", "vector type validation helpers")
    VectorMatrix = np.ndarray

VECTOR_MATRIX_NDIM: Final[int] = 2
"""Expected number of dimensions for vector matrices."""


# [nav:anchor VectorId]
VectorId = NewType("VectorId", str)
"""Unique identifier for a vector element."""


# [nav:anchor VectorValidationError]
class VectorValidationError(ValueError):
    """Raised when vector payloads fail dtype, shape, or schema validation.

    Initializes validation error with message and optional error details.

    Parameters
    ----------
    message : str
        Error message describing the validation failure.
    errors : Sequence[str] | None, optional
        List of validation error messages. Defaults to None.
    """

    def __init__(self, message: str, *, errors: Sequence[str] | None = None) -> None:
        """Initialize the validation error. See class docstring for full details."""
        super().__init__(message)
        self.errors: tuple[str, ...] = tuple(errors or (message,))


@dataclass(frozen=True, slots=True)
# [nav:anchor VectorBatch]
class VectorBatch:
    """Immutable collection of typed vectors with shared dimensionality.

    Attributes
    ----------
    ids : tuple[VectorId, ...]
        Identifiers for each vector row.
    matrix : VectorMatrix
        Two-dimensional ``float32`` matrix.

    Raises
    ------
    VectorValidationError
        If the matrix is not two dimensional, contains zero-length vectors, or
        the identifier count does not match the number of rows.
    """

    ids: tuple[VectorId, ...]
    """Identifiers for each vector row.

    Alias: none; name ``ids``.
    """
    matrix: VectorMatrix
    """Two-dimensional ``float32`` matrix.

    Alias: none; name ``matrix``.
    """

    def __post_init__(self) -> None:
        """Normalise matrix representation without enforcing ids invariants."""
        matrix = assert_vector_matrix(self.matrix)
        object.__setattr__(self, "matrix", matrix)

    @property
    def dimension(self) -> int:
        """Return the dimensionality shared by all vectors in the batch."""
        return int(self.matrix.shape[1])

    @property
    def count(self) -> int:
        """Return the number of vectors contained in the batch."""
        return len(self.ids)


# [nav:anchor assert_vector_matrix]
def assert_vector_matrix(arr: object) -> VectorMatrix:
    """Return a contiguous ``float32`` matrix derived from ``arr``.

    Parameters
    ----------
    arr : object
        Candidate matrix to validate.

    Returns
    -------
    VectorMatrix
        Contiguous ``float32`` matrix with two dimensions.

    Raises
    ------
    VectorValidationError
        If ``arr`` cannot be coerced to a two-dimensional ``float32`` matrix
        with a non-zero second dimension.
    """
    try:
        matrix = np.asarray(arr, dtype=np.float32)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        msg = "Matrix values must be numeric"
        raise VectorValidationError(msg) from exc

    if matrix.ndim != VECTOR_MATRIX_NDIM:
        msg = "Vector matrix must be two-dimensional"
        raise VectorValidationError(msg)
    if matrix.shape[1] == 0:
        msg = "Vector dimensionality must be greater than zero"
        raise VectorValidationError(msg)

    contiguous: VectorMatrix = np.ascontiguousarray(matrix, dtype=np.float32)
    return contiguous


# [nav:anchor validate_vector_batch]
def validate_vector_batch(batch: VectorBatch) -> VectorBatch:
    """Return ``batch`` after re-validating matrix invariants.

    Parameters
    ----------
    batch : VectorBatch
        Candidate batch to validate.

    Returns
    -------
    VectorBatch
        The same batch once validation succeeds.

    Raises
    ------
    VectorValidationError
        If the batch has mismatched ids or inconsistent vector dimensions.
    """
    matrix = assert_vector_matrix(batch.matrix)
    if matrix.shape[0] != len(batch.ids):
        msg = (
            "Vector id count must match matrix row count: "
            f"{len(batch.ids)} ids vs {matrix.shape[0]} rows"
        )
        raise VectorValidationError(msg)
    if matrix.shape[1] == 0:
        msg = "Vector dimensionality must be greater than zero"
        raise VectorValidationError(msg)
    if len(set(batch.ids)) != len(batch.ids):
        msg = "Vector ids must be unique"
        raise VectorValidationError(msg)
    return batch


# [nav:anchor coerce_vector_batch]
def coerce_vector_batch(records: Iterable[object]) -> VectorBatch:
    """Construct a :class:`VectorBatch` from vector payload mappings.

    Parameters
    ----------
    records : Iterable[object]
        Iterable of JSON-like mappings containing ``"key"`` and ``"vector"``
        entries. ``"vector"`` must be a one-dimensional sequence of numbers.

    Returns
    -------
    VectorBatch
        Immutable batch containing unique ids and a contiguous ``float32``
        matrix.

    Raises
    ------
    VectorValidationError
        If a record is not a mapping, ids are missing/duplicated, vectors are
        empty, non-numeric, or have inconsistent dimensionality.

    Examples
    --------
    >>> from kgfoundry_common.vector_types import coerce_vector_batch
    >>> batch = coerce_vector_batch(
    ...     [
    ...         {"key": "a", "vector": [1, 2]},
    ...         {"key": "b", "vector": [3, 4]},
    ...     ]
    ... )
    >>> batch.matrix.dtype
    dtype('float32')
    >>> batch.matrix.shape
    (2, 2)
    """
    ids: list[VectorId] = []
    seen_ids: set[VectorId] = set()
    vectors: list[list[float]] = []
    expected_dim: int | None = None

    for idx, record_obj in enumerate(records):
        if not isinstance(record_obj, Mapping):
            msg = f"Record {idx} is missing a non-empty 'key' string"
            raise VectorValidationError(msg)
        record = record_obj
        raw_key = record.get("key")
        if not isinstance(raw_key, str) or not raw_key.strip():
            msg = f"Record {idx} is missing a non-empty 'key' string"
            raise VectorValidationError(msg)

        vector_obj = record.get("vector")
        row = _coerce_vector_row(vector_obj, idx)

        if expected_dim is None:
            expected_dim = len(row)
        elif len(row) != expected_dim:
            msg = (
                f"Record {idx} has dimension {len(row)} which differs from the "
                f"expected dimension {expected_dim}"
            )
            raise VectorValidationError(msg)

        vector_id = VectorId(raw_key)
        if vector_id in seen_ids:
            msg = f"Record {idx} reuses id '{vector_id}'"
            raise VectorValidationError(msg)
        seen_ids.add(vector_id)
        ids.append(vector_id)
        vectors.append(row)

    if not ids:
        msg = "Vector payload must contain at least one record"
        raise VectorValidationError(msg)

    matrix_untyped = np.asarray(vectors, dtype=np.float32)
    matrix_contiguous: VectorMatrix = np.ascontiguousarray(matrix_untyped, dtype=np.float32)
    return VectorBatch(ids=tuple(ids), matrix=matrix_contiguous)


def _coerce_vector_row(vector_obj: object, idx: int) -> list[float]:
    """Return a typed row extracted from ``vector_obj``.

    Parameters
    ----------
    vector_obj : object
        Candidate vector payload.
    idx : int
        Zero-based index of the record, used for diagnostic messages.

    Returns
    -------
    list[float]
        Row converted to ``float32`` values.

    Raises
    ------
    VectorValidationError
        If the object cannot be converted to a one-dimensional numeric vector.
    """
    if isinstance(vector_obj, Mapping):
        msg = f"Record {idx} must provide 'vector' as a sequence, not a mapping"
        raise VectorValidationError(msg)

    try:
        array = np.asarray(vector_obj, dtype=np.float32)
    except (TypeError, ValueError) as exc:  # pragma: no cover - exercised in tests
        msg = f"Record {idx} contains non-numeric vector entries"
        raise VectorValidationError(msg) from exc

    if array.ndim != 1:
        msg = f"Record {idx} vector must be one-dimensional"
        raise VectorValidationError(msg)
    if array.size == 0:
        msg = f"Record {idx} vector must contain at least one element"
        raise VectorValidationError(msg)

    contiguous = np.ascontiguousarray(array, dtype=np.float32)
    return cast("list[float]", contiguous.astype(np.float32, copy=False).tolist())


__all__ = [
    "VectorBatch",
    "VectorId",
    "VectorMatrix",
    "VectorValidationError",
    "assert_vector_matrix",
    "coerce_vector_batch",
    "validate_vector_batch",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))
