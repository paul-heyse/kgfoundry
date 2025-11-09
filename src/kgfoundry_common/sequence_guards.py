"""Sequence access guards for observability-critical code paths.

This module provides typed helpers for validating sequence length before indexing,
emitting structured logs, metrics, and RFC 9457 Problem Details when inputs are empty.
Guards prevent raw IndexError exceptions and ensure consistent observability.

Examples
--------
>>> from kgfoundry_common.sequence_guards import first_or_error
>>> devices = (0, 1, 2)
>>> device = first_or_error(devices, context="gpu_device_selection")
>>> device
0

When sequence is empty, raises a Problem Details error:

>>> from kgfoundry_common.sequence_guards import first_or_error
>>> try:
...     first_or_error((), context="gpu_device_selection")
... except Exception as e:
...     assert "empty" in str(e).lower()
"""

# [nav:section public-api]

from __future__ import annotations

from typing import TYPE_CHECKING

from kgfoundry_common.navmap_loader import load_nav_metadata

if TYPE_CHECKING:
    from collections.abc import Sequence
else:
    import collections.abc as _abc

    Sequence = _abc.Sequence

from kgfoundry_common.errors import VectorSearchError
from kgfoundry_common.logging import get_logger, with_fields
from kgfoundry_common.problem_details import (
    build_problem_details,
    render_problem,
)

logger = get_logger(__name__)

__all__ = [
    "first_or_error",
    "first_or_error_multi_device",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# [nav:anchor first_or_error]
def first_or_error[T](
    sequence: Sequence[T],
    *,
    context: str,
    operation: str = "sequence_access",
) -> T:
    """Access first element of sequence or raise Problem Details error.

    Validates that the sequence is non-empty before indexing, ensuring
    observability instrumentation captures empty-input failures with
    structured logs and metrics.

    Parameters
    ----------
    sequence : Sequence[T]
        The sequence from which to extract the first element.
    context : str
        Human-readable description of why the sequence was accessed
        (e.g., "gpu_device_selection", "prometheus_parameter_extraction").
    operation : str, optional
        Name of the operation being performed. Defaults to "sequence_access".

    Returns
    -------
    T
        The first element of the sequence.

    Raises
    ------
    VectorSearchError
        When the sequence is empty, with RFC 9457 Problem Details payload.

    Examples
    --------
    >>> devices = [0, 1]
    >>> device = first_or_error(devices, context="gpu_devices")
    >>> device
    0

    >>> empty = []
    >>> try:
    ...     first_or_error(empty, context="gpu_devices")
    ... except Exception as e:
    ...     assert "empty" in str(e).lower()
    """
    if len(sequence) == 0:
        msg = f"Cannot access {context}: sequence is empty"
        problem = build_problem_details(
            problem_type="https://kgfoundry.dev/problems/sequence-empty",
            title="Sequence access failed",
            status=400,
            detail=msg,
            instance=f"urn:operation:{operation}:{context}",
            extensions={
                "context": context,
                "operation": operation,
                "sequence_length": 0,
            },
        )

        # Log structured error with correlation ID
        with with_fields(
            logger,
            operation=operation,
            status="error",
            context=context,
        ) as structured_logger:
            structured_logger.error(
                "Sequence access guard triggered: %s",
                msg,
                extra={
                    "problem_details": render_problem(problem),
                },
            )

        raise VectorSearchError(msg) from None

    return sequence[0]


# [nav:anchor first_or_error_multi_device]
def first_or_error_multi_device[T](
    sequence: Sequence[T],
    *,
    context: str = "device_selection",
    operation: str = "multi_device_access",
) -> T:
    """Access first element for multi-device scenarios.

    Specialized variant for FAISS multi-device GPU cloning that provides
    domain-specific error messages and metrics.

    Parameters
    ----------
    sequence : Sequence[T]
        The device list or equivalent sequence.
    context : str, optional
        Context description. Defaults to "device_selection".
    operation : str, optional
        Operation name. Defaults to "multi_device_access".

    Returns
    -------
    T
        The first element of the sequence.

    Raises
    ------
    VectorSearchError
        When the sequence is empty, with Problem Details including device context.

    Examples
    --------
    >>> gpu_indices = [<FaissIndex>]  # doctest: +SKIP
    >>> index = first_or_error_multi_device(gpu_indices, context="gpu_indices")  # doctest: +SKIP
    >>> index  # doctest: +SKIP
    <FaissIndex object at ...>
    """
    if len(sequence) == 0:
        msg = f"FAISS GPU cloning failed: {context} is empty (no devices available)"
        problem = build_problem_details(
            problem_type="https://kgfoundry.dev/problems/faiss-multi-device-empty",
            title="Multi-device GPU cloning failed",
            status=503,
            detail=msg,
            instance=f"urn:operation:{operation}:{context}",
            extensions={
                "context": context,
                "operation": operation,
                "device_count": 0,
                "remediation": (
                    "Ensure GPU resources are available and FAISS is compiled with GPU support"
                ),
            },
        )

        # Log structured error
        with with_fields(
            logger,
            operation=operation,
            status="error",
            context=context,
            device_count=0,
        ) as structured_logger:
            structured_logger.error(
                "Multi-device access guard triggered: %s",
                msg,
                extra={
                    "problem_details": render_problem(problem),
                },
            )

        raise VectorSearchError(msg) from None

    return sequence[0]
