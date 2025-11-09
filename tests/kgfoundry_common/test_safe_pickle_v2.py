"""Tests for secure pickle with HMAC signing and allow-list validation."""

from __future__ import annotations

import io
import os
from typing import TYPE_CHECKING, ParamSpec, TypeVar, cast

import pytest

from kgfoundry_common.safe_pickle_v2 import (
    SignedPickleWrapper,
    UnsafeSerializationError,
    create_unsigned_pickle_payload,
)

P = ParamSpec("P")
R = TypeVar("R")


if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable

    from _pytest.logging import LogCaptureFixture

    def fixture(
        *args: object, **kwargs: object
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """Create a pytest fixture.

        Parameters
        ----------
        *args : object
            Positional arguments for pytest.fixture.
        **kwargs : object
            Keyword arguments for pytest.fixture.

        Returns
        -------
        Callable[[Callable[P, R]], Callable[P, R]]
            Decorator function for creating fixtures.
        """
        ...

else:  # pragma: no cover - pytest provides runtime decorator
    fixture = pytest.fixture


@fixture
def signing_key() -> bytes:
    """Provide a valid signing key.

    Returns
    -------
    bytes
        Random 32-byte signing key.
    """
    return os.urandom(32)


@fixture
def wrapper(signing_key: bytes) -> SignedPickleWrapper:
    """Provide a wrapper instance with a random signing key.

    Parameters
    ----------
    signing_key : bytes
        Signing key to use.

    Returns
    -------
    SignedPickleWrapper
        Configured wrapper instance.
    """
    return SignedPickleWrapper(signing_key)


class TestSignedPickleWrapper:
    """Test suite for SignedPickleWrapper."""

    ALLOWED_VALUES: tuple[object, ...] = (
        {"key": "value"},
        {"nested": {"dict": ["list", 42, 3.14, True, None]}},
        [1, 2, 3],
        "string",
        42,
        3.14,
        True,
        None,
        [],
        {},
    )

    def test_dump_and_load_allowed_types(self, wrapper: SignedPickleWrapper) -> None:
        """Test that allowed types round-trip correctly."""
        for data in self.ALLOWED_VALUES:
            buffer = io.BytesIO()
            wrapper.dump(data, buffer)
            buffer.seek(0)
            loaded = wrapper.load(buffer)
            assert loaded == data

    def test_signature_verification_success(self, wrapper: SignedPickleWrapper) -> None:
        """Test that valid signatures pass verification."""
        data = {"test": "data"}
        buffer = io.BytesIO()
        wrapper.dump(data, buffer)

        # Signature should be verified on load
        buffer.seek(0)
        loaded = wrapper.load(buffer)
        assert loaded == data

    def test_signature_verification_fails_on_tampering(
        self,
        wrapper: SignedPickleWrapper,
    ) -> None:
        """Test that tampering with payload is detected."""
        data = {"test": "data"}
        buffer = io.BytesIO()
        wrapper.dump(data, buffer)

        # Tamper with the payload
        tampered_data = buffer.getvalue()
        tampered_data = tampered_data[:50] + b"TAMPERED" + tampered_data[58:]

        tampered_buffer = io.BytesIO(tampered_data)
        with pytest.raises(
            UnsafeSerializationError, match="signature verification failed"
        ):
            wrapper.load(tampered_buffer)

    def test_signature_verification_fails_on_truncation(
        self,
        wrapper: SignedPickleWrapper,
    ) -> None:
        """Test that truncated payload is detected."""
        data = {"test": "data"}
        buffer = io.BytesIO()
        wrapper.dump(data, buffer)

        # Truncate payload
        truncated = buffer.getvalue()[:10]
        truncated_buffer = io.BytesIO(truncated)

        with pytest.raises(
            UnsafeSerializationError,
            match=r"(too short|signature verification)",
        ):
            wrapper.load(truncated_buffer)

    def test_different_key_fails_verification(self, signing_key: bytes) -> None:
        """Test that signatures from different keys fail verification."""
        wrapper1 = SignedPickleWrapper(signing_key)
        wrapper2 = SignedPickleWrapper(os.urandom(32))

        data = {"test": "data"}
        buffer = io.BytesIO()
        wrapper1.dump(data, buffer)

        buffer.seek(0)
        with pytest.raises(
            UnsafeSerializationError, match="signature verification failed"
        ):
            wrapper2.load(buffer)

    def test_disallowed_type_rejected_on_dump(
        self, wrapper: SignedPickleWrapper
    ) -> None:
        """Test that disallowed types are rejected during dump."""

        class CustomClass:
            """Custom class for disallowed type testing."""

        with pytest.raises(ValueError, match="not allowed"):
            wrapper.dump(CustomClass(), io.BytesIO())

    def test_disallowed_type_rejected_on_load(self) -> None:
        """Test that disallowed types are rejected during load."""

        # Create a pickle with a disallowed type (manually, for testing)
        class CustomClass:
            """Custom class for disallowed type testing."""

        obj = CustomClass()
        pickled = create_unsigned_pickle_payload(obj)

        # Try to load it - should fail due to allow-list
        key = os.urandom(32)
        wrapper = SignedPickleWrapper(key)

        # Add a fake signature (32 bytes of zeros)
        signed_data = b"\x00" * 32 + pickled
        buffer = io.BytesIO(signed_data)

        with pytest.raises(
            UnsafeSerializationError,
            match=r"(Deserialization blocked|not in allow-list|signature verification)",
        ):
            wrapper.load(buffer)

    def test_short_key_warning_logged(self, caplog: LogCaptureFixture) -> None:
        """Test that short keys generate a warning."""
        short_key = b"short_key"
        with caplog.at_level("WARNING"):
            SignedPickleWrapper(short_key)

        assert any(
            "Signing key < 32 bytes" in record.getMessage() for record in caplog.records
        )

    def test_nested_container_depth_limit(self, wrapper: SignedPickleWrapper) -> None:
        """Test that deeply nested structures are rejected."""
        # Create very deeply nested structure
        data: dict[str, object] = {"level": 0}
        current: dict[str, object] = data
        for i in range(150):
            current["nested"] = {"level": i + 1}
            current = cast("dict[str, object]", current["nested"])

        with pytest.raises(ValueError, match="exceeds maximum depth"):
            wrapper.dump(data, io.BytesIO())


class TestUnsafeSerializationError:
    """Test suite for error reporting."""

    def test_error_with_reason(self) -> None:
        """Test that error captures reason."""
        error = UnsafeSerializationError("Test message", reason="test_reason")
        assert error.reason == "test_reason"

    def test_error_without_reason(self) -> None:
        """Test that error works without reason."""
        error = UnsafeSerializationError("Test message")
        assert error.reason is None


class TestPickleRoundTrip:
    """Integration tests for pickle round-tripping."""

    def test_complex_nested_structure(self, wrapper: SignedPickleWrapper) -> None:
        """Test complex nested structures round-trip."""
        data = {
            "users": [
                {"name": "Alice", "age": 30, "active": True},
                {"name": "Bob", "age": None, "active": False},
            ],
            "metadata": {
                "version": 1,
                "count": 2,
                "tags": ["prod", "test"],
                "config": {"debug": False, "level": 3},
            },
        }

        buffer = io.BytesIO()
        wrapper.dump(data, buffer)

        buffer.seek(0)
        loaded = cast("dict[str, object]", wrapper.load(buffer))
        assert loaded == data

        users = cast("list[dict[str, object]]", loaded["users"])
        assert users[0]["name"] == "Alice"

        metadata = cast("dict[str, object]", loaded["metadata"])
        config = cast("dict[str, object]", metadata["config"])
        assert config["debug"] is False
