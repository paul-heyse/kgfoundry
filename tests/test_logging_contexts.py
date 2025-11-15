"""Tests for hardened logging contexts with immutability and type safety.

This module verifies that LogContextExtra uses frozen dataclasses correctly, provides safe accessor
patterns, and integrates with RFC 9457 Problem Details.
"""

from __future__ import annotations

import json
import logging
from io import StringIO
from typing import TYPE_CHECKING, cast

from tools.shared.cli import (
    CLI_ENVELOPE_SCHEMA_ID,
    CLI_ENVELOPE_SCHEMA_VERSION,
    CliErrorEntry,
    new_cli_envelope,
)

from kgfoundry_common.logging import (
    CorrelationContext,
    JsonFormatter,
    LogContextExtra,
    LoggerAdapter,
    get_correlation_id,
    with_fields,
)
from tests.helpers import assert_frozen_attribute

if TYPE_CHECKING:
    from kgfoundry_common.problem_details import ProblemDetails
else:  # pragma: no cover - runtime stand-in for typing alias
    ProblemDetails = dict[str, object]


class TestLogContextExtraImmutability:
    """Test that LogContextExtra is truly immutable (frozen)."""

    def test_context_is_frozen(self) -> None:
        """Frozen dataclass prevents field mutation."""
        ctx = LogContextExtra(correlation_id="req-123", operation="search")
        # Attempting to mutate should raise FrozenInstanceError
        assert_frozen_attribute(ctx, "correlation_id", value="req-456")

    def test_with_methods_return_new_instances(self) -> None:
        """with_* methods return new instances, not modify in place."""
        ctx1 = LogContextExtra(correlation_id="req-123")
        ctx2 = ctx1.with_operation("search")

        # Original is unchanged
        assert ctx1.operation is None
        # New instance has updated field
        assert ctx2.operation == "search"
        # Correlation ID is preserved
        assert ctx2.correlation_id == "req-123"

    def test_chained_with_methods(self) -> None:
        """Multiple with_* calls can be chained."""
        ctx = (
            LogContextExtra()
            .with_correlation_id("req-123")
            .with_operation("search")
            .with_status("success")
            .with_duration_ms(42.5)
        )

        assert ctx.correlation_id == "req-123"
        assert ctx.operation == "search"
        assert ctx.status == "success"
        assert ctx.duration_ms == 42.5


class TestLogContextExtraConversion:
    """Test conversion of LogContextExtra to dict for logging."""

    def test_to_dict_excludes_none_values(self) -> None:
        """to_dict excludes None fields to avoid verbose logs."""
        ctx = LogContextExtra(correlation_id="req-123", operation="search", status=None)
        data = cast("dict[str, str | float | None]", ctx.to_dict())

        assert data == {"correlation_id": "req-123", "operation": "search"}
        assert "status" not in data

    def test_to_dict_empty_context(self) -> None:
        """Empty context converts to empty dict."""
        ctx = LogContextExtra()
        data = cast("dict[str, str | float | None]", ctx.to_dict())
        assert data == {}

    def test_to_dict_all_fields(self) -> None:
        """All non-None fields appear in dict."""
        ctx = LogContextExtra(
            correlation_id="req-123",
            operation="build",
            status="in_progress",
            duration_ms=0.5,
            service="docs-pipeline",
            endpoint="/api/docs",
        )
        data = cast("dict[str, str | float | None]", ctx.to_dict())

        assert len(data) == 6
        assert data.get("correlation_id") == "req-123"
        assert data.get("service") == "docs-pipeline"


class TestLoggerAdapterWithLogContextExtra:
    """Test LoggerAdapter handles LogContextExtra dataclass correctly."""

    def test_logger_adapter_accepts_log_context_extra(self) -> None:
        """LoggerAdapter can be initialized with LogContextExtra."""
        ctx = LogContextExtra(correlation_id="req-123", operation="search")
        base_logger = logging.getLogger("test_adapter")
        adapter = LoggerAdapter(base_logger, ctx)

        assert adapter.extra is not None
        assert isinstance(adapter.extra, LogContextExtra)

    def test_logging_with_context_extra(self) -> None:
        """Logging with LogContextExtra properly injects fields."""
        stream = StringIO()
        formatter = JsonFormatter()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(formatter)

        base_logger = logging.getLogger("test_context_logging")
        base_logger.handlers.clear()
        base_logger.addHandler(handler)
        base_logger.setLevel(logging.INFO)

        ctx = LogContextExtra(correlation_id="req-123", operation="search")
        adapter = LoggerAdapter(base_logger, ctx)
        adapter.info("Test message")

        output = stream.getvalue().strip()
        parsed = cast("dict[str, object]", json.loads(output))
        assert parsed.get("correlation_id") == "req-123"
        assert parsed.get("operation") == "search"
        assert parsed.get("message") == "Test message"


class TestLogContextExtraDoctest:
    """Verify doctest examples in LogContextExtra docstring work correctly."""

    def test_doctest_context_creation(self) -> None:
        """Example: Create context with initial fields."""
        ctx = LogContextExtra(correlation_id="req-123", operation="search")
        assert ctx.correlation_id == "req-123"
        assert ctx.operation == "search"

    def test_doctest_with_status(self) -> None:
        """Example: Update status immutably."""
        ctx = LogContextExtra(correlation_id="req-123", operation="search")
        ctx_with_status = ctx.with_status("success")
        assert ctx_with_status.status == "success"
        # Original unchanged
        assert ctx.status is None

    def test_doctest_immutability_guarantee(self) -> None:
        """Example: Original context never mutated by with_* methods."""
        ctx = LogContextExtra()
        _ = ctx.with_status("success")
        assert ctx.status is None


class TestSafeAccessorPatterns:
    """Test safe patterns for accessing optional fields."""

    def test_get_with_default(self) -> None:
        """Dict.get() works for safely accessing optional fields."""
        ctx = LogContextExtra(correlation_id="req-123")
        data = cast("dict[str, str | float | None]", ctx.to_dict())

        # Safe access with .get()
        correlation: str | float | None = data.get("correlation_id")
        status: str | float | None = data.get("status", "unknown")

        assert correlation == "req-123"
        assert status == "unknown"

    def test_optional_field_in_to_dict(self) -> None:
        """Check presence of optional field before access."""
        ctx = LogContextExtra(operation="search")
        data = cast("dict[str, str | float | None]", ctx.to_dict())

        # Use ternary for clarity
        problem: str | float | None = data.get("problem")

        assert problem is None
        assert "operation" in data


class TestCliErrorEntryConstructor:
    """Test safe construction of CliErrorEntry."""

    def test_cli_error_entry_with_required_fields(self) -> None:
        """CliErrorEntry ensures all required fields are set."""
        error = CliErrorEntry(status="error", message="Failed to build")

        assert error.status == "error"
        assert error.message == "Failed to build"
        assert error.file is None or isinstance(error.file, str)

    def test_cli_error_entry_with_optional_file(self) -> None:
        """Optional file field can be included."""
        error = CliErrorEntry(status="error", message="Failed", file="test.py")

        assert error.file == "test.py"
        assert error.status == "error"
        assert error.message == "Failed"


class TestCliEnvelopeConstructor:
    """Test safe construction of CliEnvelope with explicit required/optional fields."""

    def test_new_cli_envelope_minimal(self) -> None:
        """Helper with minimal required fields only."""
        envelope = new_cli_envelope(command="build", status="success")

        assert envelope.schema_version == CLI_ENVELOPE_SCHEMA_VERSION
        assert envelope.schema_id == CLI_ENVELOPE_SCHEMA_ID
        assert envelope.status == "success"
        assert envelope.command == "build"
        assert envelope.generated_at is not None
        # Optional fields should have defaults
        assert not envelope.subcommand

    def test_new_cli_envelope_with_subcommand(self) -> None:
        """Helper includes subcommand when provided."""
        envelope = new_cli_envelope(command="build", status="success", subcommand="docstrings")

        assert envelope.status == "success"
        assert envelope.subcommand == "docstrings"

    def test_new_cli_envelope_datetime_generated(self) -> None:
        """Helper automatically generates current timestamp."""
        envelope = new_cli_envelope(command="build", status="success")

        # generatedAt is ISO format string
        assert isinstance(envelope.generated_at, str)
        assert "T" in envelope.generated_at  # ISO format
        # UTC timezone indicated by +00:00 or Z suffix
        assert envelope.generated_at.endswith(("+00:00", "Z"))


class TestLoggingIntegration:
    """Test integration with Problem Details and correlation IDs."""

    def test_correlation_context_manager(self) -> None:
        """CorrelationContext sets and clears correlation_id."""
        assert get_correlation_id() is None

        with CorrelationContext("req-123"):
            assert get_correlation_id() == "req-123"
            # Verify with_fields works in context
            with_fields_adapter = with_fields(logging.getLogger("test"), correlation_id="req-123")
            assert with_fields_adapter is not None

        assert get_correlation_id() is None
