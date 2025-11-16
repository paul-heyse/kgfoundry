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
from tests._helpers import assertions
from tests.helpers import assert_frozen_attribute

if TYPE_CHECKING:
    from kgfoundry_common.problem_details import ProblemDetails
else:  # pragma: no cover - runtime stand-in for typing alias
    ProblemDetails = dict[str, object]


def test_context_is_frozen() -> None:
    """Frozen dataclass prevents field mutation."""
    ctx = LogContextExtra(correlation_id="req-123", operation="search")
    # Attempting to mutate should raise FrozenInstanceError
    assert_frozen_attribute(ctx, "correlation_id", value="req-456")


def test_with_methods_return_new_instances() -> None:
    """with_* methods return new instances, not modify in place."""
    ctx1 = LogContextExtra(correlation_id="req-123")
    ctx2 = ctx1.with_operation("search")

    # Original is unchanged
    assertions.expect_equal(ctx1.operation, None)
    # New instance has updated field
    assertions.expect_equal(ctx2.operation, "search")
    # Correlation ID is preserved
    assertions.expect_equal(ctx2.correlation_id, "req-123")


def test_chained_with_methods() -> None:
    """Multiple with_* calls can be chained."""
    ctx = (
        LogContextExtra()
        .with_correlation_id("req-123")
        .with_operation("search")
        .with_status("success")
        .with_duration_ms(42.5)
    )

    assertions.expect_equal(ctx.correlation_id, "req-123")
    assertions.expect_equal(ctx.operation, "search")
    assertions.expect_equal(ctx.status, "success")
    assertions.expect_equal(ctx.duration_ms, 42.5)


def test_to_dict_excludes_none_values() -> None:
    """to_dict excludes None fields to avoid verbose logs."""
    ctx = LogContextExtra(correlation_id="req-123", operation="search", status=None)
    data = cast("dict[str, str | float | None]", ctx.to_dict())

    assertions.expect_mapping_equal(data, {"correlation_id": "req-123", "operation": "search"})
    assertions.expect_false("status" in data, reason="None values should be excluded from dict")


def test_to_dict_empty_context() -> None:
    """Empty context converts to empty dict."""
    ctx = LogContextExtra()
    data = cast("dict[str, str | float | None]", ctx.to_dict())
    assertions.expect_mapping_equal(data, {})


def test_to_dict_all_fields() -> None:
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

    assertions.expect_equal(len(data), 6)
    assertions.expect_equal(data.get("correlation_id"), "req-123")
    assertions.expect_equal(data.get("service"), "docs-pipeline")


def test_logger_adapter_accepts_log_context_extra() -> None:
    """LoggerAdapter can be initialized with LogContextExtra."""
    ctx = LogContextExtra(correlation_id="req-123", operation="search")
    base_logger = logging.getLogger("test_adapter")
    adapter = LoggerAdapter(base_logger, ctx)

    assertions.expect_true(adapter.extra is not None, reason="adapter should have extra context")
    assertions.expect_true(
        isinstance(adapter.extra, LogContextExtra), reason="extra should be LogContextExtra"
    )


def test_logging_with_context_extra() -> None:
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
    assertions.expect_equal(parsed.get("correlation_id"), "req-123")
    assertions.expect_equal(parsed.get("operation"), "search")
    assertions.expect_equal(parsed.get("message"), "Test message")


def test_doctest_context_creation() -> None:
    """Example: Create context with initial fields."""
    ctx = LogContextExtra(correlation_id="req-123", operation="search")
    assertions.expect_equal(ctx.correlation_id, "req-123")
    assertions.expect_equal(ctx.operation, "search")


def test_doctest_with_status() -> None:
    """Example: Update status immutably."""
    ctx = LogContextExtra(correlation_id="req-123", operation="search")
    ctx_with_status = ctx.with_status("success")
    assertions.expect_equal(ctx_with_status.status, "success")
    # Original unchanged
    assertions.expect_equal(ctx.status, None)


def test_doctest_immutability_guarantee() -> None:
    """Example: Original context never mutated by with_* methods."""
    ctx = LogContextExtra()
    _ = ctx.with_status("success")
    assertions.expect_equal(ctx.status, None)


def test_get_with_default() -> None:
    """Dict.get() works for safely accessing optional fields."""
    ctx = LogContextExtra(correlation_id="req-123")
    data = cast("dict[str, str | float | None]", ctx.to_dict())

    # Safe access with .get()
    correlation: str | float | None = data.get("correlation_id")
    status: str | float | None = data.get("status", "unknown")

    assertions.expect_equal(correlation, "req-123")
    assertions.expect_equal(status, "unknown")


def test_optional_field_in_to_dict() -> None:
    """Check presence of optional field before access."""
    ctx = LogContextExtra(operation="search")
    data = cast("dict[str, str | float | None]", ctx.to_dict())

    # Use ternary for clarity
    problem: str | float | None = data.get("problem")

    assertions.expect_equal(problem, None)
    assertions.expect_true("operation" in data, reason="operation should be in data")


def test_cli_error_entry_with_required_fields() -> None:
    """CliErrorEntry ensures all required fields are set."""
    error = CliErrorEntry(status="error", message="Failed to build")

    assertions.expect_equal(error.status, "error")
    assertions.expect_equal(error.message, "Failed to build")
    assertions.expect_true(
        error.file is None or isinstance(error.file, str), reason="file should be None or str"
    )


def test_cli_error_entry_with_optional_file() -> None:
    """Optional file field can be included."""
    error = CliErrorEntry(status="error", message="Failed", file="test.py")

    assertions.expect_equal(error.file, "test.py")
    assertions.expect_equal(error.status, "error")
    assertions.expect_equal(error.message, "Failed")


def test_new_cli_envelope_minimal() -> None:
    """Helper with minimal required fields only."""
    envelope = new_cli_envelope(command="build", status="success")

    assertions.expect_equal(envelope.schema_version, CLI_ENVELOPE_SCHEMA_VERSION)
    assertions.expect_equal(envelope.schema_id, CLI_ENVELOPE_SCHEMA_ID)
    assertions.expect_equal(envelope.status, "success")
    assertions.expect_equal(envelope.command, "build")
    assertions.expect_true(envelope.generated_at is not None, reason="generated_at should be set")
    # Optional fields should have defaults
    assertions.expect_false(envelope.subcommand, reason="subcommand should default to empty")


def test_new_cli_envelope_with_subcommand() -> None:
    """Helper includes subcommand when provided."""
    envelope = new_cli_envelope(command="build", status="success", subcommand="docstrings")

    assertions.expect_equal(envelope.status, "success")
    assertions.expect_equal(envelope.subcommand, "docstrings")


def test_new_cli_envelope_datetime_generated() -> None:
    """Helper automatically generates current timestamp."""
    envelope = new_cli_envelope(command="build", status="success")

    # generatedAt is ISO format string
    assertions.expect_true(
        isinstance(envelope.generated_at, str), reason="generated_at should be str"
    )
    assertions.expect_true("T" in envelope.generated_at, reason="ISO format should contain T")
    # UTC timezone indicated by +00:00 or Z suffix
    assertions.expect_true(
        envelope.generated_at.endswith(("+00:00", "Z")), reason="should end with UTC timezone"
    )


def test_correlation_context_manager() -> None:
    """CorrelationContext sets and clears correlation_id."""
    assertions.expect_equal(get_correlation_id(), None)

    with CorrelationContext("req-123"):
        assertions.expect_equal(get_correlation_id(), "req-123")
        # Verify with_fields works in context
        with_fields_adapter = with_fields(logging.getLogger("test"), correlation_id="req-123")
        assertions.expect_true(
            with_fields_adapter is not None, reason="with_fields should return adapter"
        )

    assertions.expect_equal(get_correlation_id(), None)
