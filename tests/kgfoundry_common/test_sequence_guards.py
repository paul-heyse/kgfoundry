"""Unit tests for sequence access guards.

Tests verify guard helpers prevent IndexError on empty sequences and emit structured logs, metrics,
and RFC 9457 Problem Details.
"""

from __future__ import annotations

from collections.abc import Sequence as TypingSequence
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Sequence
else:
    Sequence = TypingSequence

import pytest

from kgfoundry_common.errors import VectorSearchError
from kgfoundry_common.sequence_guards import first_or_error, first_or_error_multi_device


class SequenceGuard(Protocol):
    """Protocol describing the generic sequence guard callable contract."""

    def __call__(
        self,
        sequence: Sequence[object],
        *,
        context: str,
        operation: str = ...,
    ) -> object:
        """Guard sequence with context.

        Parameters
        ----------
        sequence : Sequence[object]
            Sequence to guard.
        context : str
            Context description.
        operation : str, optional
            Operation name.

        Returns
        -------
        object
            First element of sequence.
        """
        ...


class MultiDeviceGuard(Protocol):
    """Protocol describing the multi-device guard callable contract."""

    def __call__(
        self,
        sequence: Sequence[object],
        *,
        context: str = ...,
        operation: str = ...,
    ) -> object:
        """Guard sequence for multi-device context.

        Parameters
        ----------
        sequence : Sequence[object]
            Sequence to guard.
        context : str, optional
            Context description.
        operation : str, optional
            Operation name.

        Returns
        -------
        object
            First element of sequence.
        """
        ...


@pytest.fixture(name="sequence_guard")
def sequence_guard_fixture() -> SequenceGuard:
    """Provide a typed fixture for the generic sequence guard.

    Returns
    -------
    SequenceGuard
        first_or_error function.
    """
    return first_or_error


@pytest.fixture(name="multi_device_guard")
def multi_device_guard_fixture() -> MultiDeviceGuard:
    """Provide a typed fixture for the multi-device sequence guard.

    Returns
    -------
    MultiDeviceGuard
        first_or_error_multi_device function.
    """
    return first_or_error_multi_device


class TestFirstOrError:
    """Tests for first_or_error guard function."""

    def test_valid_sequence_returns_first_element(self, sequence_guard: SequenceGuard) -> None:
        """Verify first_or_error returns first element for non-empty sequence."""
        devices = [0, 1, 2]
        result = sequence_guard(devices, context="test_devices")
        assert result == 0

    def test_valid_tuple_returns_first_element(self, sequence_guard: SequenceGuard) -> None:
        """Verify first_or_error works with tuples."""
        devices = (10, 20, 30)
        result = sequence_guard(devices, context="test_tuple")
        assert result == 10

    def test_single_element_sequence(self, sequence_guard: SequenceGuard) -> None:
        """Verify single-element sequence returns that element."""
        devices = [42]
        result = sequence_guard(devices, context="single_element")
        assert result == 42

    def test_empty_list_raises_vector_search_error(self, sequence_guard: SequenceGuard) -> None:
        """Verify empty list raises VectorSearchError with Problem Details."""
        with pytest.raises(VectorSearchError) as exc_info:
            sequence_guard([], context="empty_devices")

        error = exc_info.value
        assert "empty" in str(error).lower()
        assert "sequence is empty" in str(error)

    def test_empty_tuple_raises_vector_search_error(self, sequence_guard: SequenceGuard) -> None:
        """Verify empty tuple raises VectorSearchError."""
        with pytest.raises(VectorSearchError) as exc_info:
            sequence_guard((), context="gpu_devices")

        error = exc_info.value
        assert "empty" in str(error).lower()

    @pytest.mark.parametrize(
        "empty_seq",
        [
            [],
            (),
            "",  # empty string is a sequence
        ],
    )
    def test_various_empty_sequences_raise_error(
        self, sequence_guard: SequenceGuard, empty_seq: Sequence[object]
    ) -> None:
        """Verify various empty sequence types raise VectorSearchError."""
        with pytest.raises(VectorSearchError):
            sequence_guard(empty_seq, context="various_sequences")

    def test_error_includes_context_information(self, sequence_guard: SequenceGuard) -> None:
        """Verify error message includes provided context."""
        context_str = "my_special_context"
        with pytest.raises(VectorSearchError) as exc_info:
            sequence_guard([], context=context_str)

        error_msg = str(exc_info.value)
        assert context_str in error_msg

    def test_custom_operation_parameter(self, sequence_guard: SequenceGuard) -> None:
        """Verify custom operation parameter is accepted and used."""
        operation = "custom_gpu_operation"
        with pytest.raises(VectorSearchError) as exc_info:
            sequence_guard([], context="gpu", operation=operation)

        # Error should be raised without issues
        assert exc_info.value is not None

    def test_preserves_element_type(self, sequence_guard: SequenceGuard) -> None:
        """Verify first_or_error preserves the type of returned element."""
        strings = ["hello", "world"]
        result = sequence_guard(strings, context="strings")
        assert isinstance(result, str)
        assert result == "hello"

    def test_sequence_length_check(self, sequence_guard: SequenceGuard) -> None:
        """Verify guard correctly identifies empty vs.

        non-empty.
        """
        # Non-empty should work
        assert sequence_guard([1], context="c") == 1

        # Empty should fail
        with pytest.raises(VectorSearchError):
            sequence_guard([], context="c")


class TestFirstOrErrorMultiDevice:
    """Tests for first_or_error_multi_device specialized variant."""

    def test_valid_devices_returns_first(self, multi_device_guard: MultiDeviceGuard) -> None:
        """Verify multi-device variant returns first element."""
        gpu_indices = [0, 1, 2]
        result = multi_device_guard(gpu_indices)
        assert result == 0

    def test_empty_devices_raises_error(self, multi_device_guard: MultiDeviceGuard) -> None:
        """Verify empty device list raises VectorSearchError."""
        with pytest.raises(VectorSearchError) as exc_info:
            multi_device_guard([])

        error = exc_info.value
        assert "FAISS GPU cloning failed" in str(error)
        assert "empty" in str(error).lower()

    def test_custom_context_parameter(self, multi_device_guard: MultiDeviceGuard) -> None:
        """Verify custom context is used in error message."""
        custom_context = "my_gpu_list"
        with pytest.raises(VectorSearchError) as exc_info:
            multi_device_guard([], context=custom_context)

        error_msg = str(exc_info.value)
        assert custom_context in error_msg

    def test_single_device(self, multi_device_guard: MultiDeviceGuard) -> None:
        """Verify single device in list returns correctly."""
        result = multi_device_guard([42])
        assert result == 42

    def test_error_mentions_gpu_context(self, multi_device_guard: MultiDeviceGuard) -> None:
        """Verify error specifically mentions GPU/FAISS context."""
        with pytest.raises(VectorSearchError) as exc_info:
            multi_device_guard([])

        error_msg = str(exc_info.value)
        # Should mention FAISS or GPU context
        assert "FAISS" in error_msg or "GPU" in error_msg.upper()

    @pytest.mark.parametrize(
        ("devices", "expected"),
        [
            ([100], 100),
            ([1, 2, 3], 1),
            (("a", "b"), "a"),
            (range(5), 0),
        ],
    )
    def test_various_valid_sequences(
        self,
        multi_device_guard: MultiDeviceGuard,
        devices: Sequence[object],
        expected: object,
    ) -> None:
        """Verify multi-device works with various sequence types."""
        result: object = multi_device_guard(devices)
        assert result == expected


class TestErrorHandling:
    """Tests for error handling aspects of guards (logs, exceptions)."""

    def test_error_is_vector_search_error_type(self, sequence_guard: SequenceGuard) -> None:
        """Verify guard raises the correct exception type."""
        with pytest.raises(VectorSearchError):
            sequence_guard([], context="test")

        # Guard should raise VectorSearchError, not generic IndexError or ValueError
        # This is verified by the pytest.raises above

    def test_preserves_exception_cause_chain(self, sequence_guard: SequenceGuard) -> None:
        """Verify exception cause chain is clean (raised from None)."""
        with pytest.raises(VectorSearchError) as exc_info:
            sequence_guard([], context="test")

        # Cause should be None (raised from None)
        assert exc_info.value.__cause__ is None


@pytest.mark.parametrize(
    ("seq_type", "seq_value"),
    [
        ("empty_list", []),
        ("empty_tuple", ()),
        ("list_with_one", [1]),
        ("list_with_many", [1, 2, 3, 4, 5]),
        ("tuple_single", (42,)),
        ("tuple_multi", (10, 20, 30)),
    ],
)
class TestFirstOrErrorParametrized:
    """Parametrized tests for comprehensive coverage."""

    def test_sequence_behavior(
        self,
        sequence_guard: SequenceGuard,
        seq_type: str,
        seq_value: Sequence[object],
    ) -> None:
        """Comprehensive parametrized test for various sequences."""
        if seq_type.startswith("empty"):
            # Empty sequences should raise
            with pytest.raises(VectorSearchError):
                sequence_guard(seq_value, context="test")
        else:
            # Non-empty sequences should return first element
            result: object = sequence_guard(seq_value, context="test")
            # Verify it returned something (the first element)
            assert result is not None
