"""Typed NumPy helpers shared across vector search modules."""

# [nav:section public-api]

from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast

import numpy as np

from kgfoundry_common.navmap_loader import load_nav_metadata

if TYPE_CHECKING:  # pragma: no cover - typing only
    import numpy.typing as npt

    type FloatMatrix = npt.NDArray[np.float32]
    type FloatVector = npt.NDArray[np.float32]
    type IntVector = npt.NDArray[np.int64]
    type Float64Matrix = npt.NDArray[np.float64]
else:  # pragma: no cover - runtime fallback
    FloatMatrix = np.ndarray
    FloatVector = np.ndarray
    IntVector = np.ndarray
    Float64Matrix = np.ndarray

# [nav:anchor MIN_EPSILON]
MIN_EPSILON: Final[float] = 1e-9
"""Lower bound used to prevent division by zero during normalisation."""


# [nav:anchor normalize_l2]
def normalize_l2(
    matrix: FloatMatrix,
    *,
    axis: int = 1,
    epsilon: float = MIN_EPSILON,
) -> FloatMatrix:
    """Return an L2-normalised copy of ``matrix`` with numerical safeguards.

    Parameters
    ----------
    matrix : FloatMatrix
        Input vectors that are expected to be contiguous ``float32`` values.
    axis : int, optional
        Axis along which norms are computed. Defaults to ``1`` for row vectors.
    epsilon : float, optional
        Minimum norm value to clamp to for zero or denormalised rows.
        Defaults to MIN_EPSILON.

    Returns
    -------
    FloatMatrix
        L2-normalized matrix with same shape as input.

    Examples
    --------
    >>> import numpy as np
    >>> from kgfoundry_common.numpy_typing import normalize_l2
    >>> mat = np.array([[3.0, 4.0], [0.0, 0.0]], dtype=np.float32)
    >>> normalize_l2(mat)
    array([[0.6, 0.8],
           [0. , 0. ]], dtype=float32)

    >>> normalize_l2(np.zeros((1, 4), dtype=np.float32))
    array([[0., 0., 0., 0.]], dtype=float32)
    """
    matrix_f32: FloatMatrix = np.asarray(matrix, dtype=np.float32, order="C")
    norms_untyped: Float64Matrix = np.linalg.norm(matrix_f32, axis=axis, keepdims=True)
    norms: FloatMatrix = norms_untyped.astype(np.float32, copy=False)
    np.maximum(norms, epsilon, out=norms)
    np.divide(matrix_f32, norms, out=matrix_f32)
    return matrix_f32


# [nav:anchor safe_argpartition]
def safe_argpartition(values: FloatVector, k: int) -> IntVector:
    """Return indices of the smallest ``k`` values with predictable ordering.

    Parameters
    ----------
    values : FloatVector
        Input vector to partition.
    k : int
        Number of smallest values to select.

    Returns
    -------
    IntVector
        Indices of the smallest k values, sorted.

    Raises
    ------
    ValueError
        If k is negative.
    """
    if k < 0:
        msg = "k must be non-negative"
        raise ValueError(msg)

    values_array: FloatVector = np.asarray(values, dtype=np.float32, order="C")
    if k == 0 or values_array.size == 0:
        return cast("IntVector", np.empty(0, dtype=np.int64))

    trimmed_k = min(k, values_array.size)
    partition = np.argpartition(values_array, trimmed_k - 1)[:trimmed_k]
    return np.sort(partition).astype(np.int64, copy=False)


# [nav:anchor topk_indices]
def topk_indices(scores: FloatVector, k: int) -> IntVector:
    """Return indices of the top ``k`` scores sorted by descending score.

    Parameters
    ----------
    scores : FloatVector
        Input score vector.
    k : int
        Number of top scores to select.

    Returns
    -------
    IntVector
        Indices of the top k scores, sorted by descending score.

    Raises
    ------
    ValueError
        If k is not positive.
    """
    if k <= 0:
        msg = "k must be positive"
        raise ValueError(msg)

    scores_array: FloatVector = np.asarray(scores, dtype=np.float32, order="C")
    total = scores_array.size
    if total == 0:
        return cast("IntVector", np.empty(0, dtype=np.int64))

    trimmed_k = min(k, total)
    score_list = cast("list[float]", scores_array.astype(np.float64, copy=False).tolist())

    def sort_key(idx: int) -> tuple[float, int]:
        """Return sort key tuple for index ranking.

        Parameters
        ----------
        idx : int
            Index into score_list.

        Returns
        -------
        tuple[float, int]
            Tuple of (score, negative_index) for stable sorting.
        """
        return (float(score_list[idx]), -idx)

    ranked = sorted(range(total), key=sort_key, reverse=True)[:trimmed_k]
    ranked_array: IntVector = np.asarray(ranked, dtype=np.int64)
    return ranked_array


__all__ = [
    "MIN_EPSILON",
    "FloatMatrix",
    "FloatVector",
    "IntVector",
    "normalize_l2",
    "safe_argpartition",
    "topk_indices",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))
