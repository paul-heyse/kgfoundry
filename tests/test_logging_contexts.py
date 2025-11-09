"""Tests for hardened logging contexts with immutability and type safety.

This module verifies that LogContextExtra uses frozen dataclasses correctly, provides safe accessor
patterns, and integrates with RFC 9457 Problem Details.
"""

from __future__ import annotations

import json
import logging
from io import StringIO
from typing import TYPE_CHECKING, cast

from tools.docstring_builder.models import (
    CLI_SCHEMA_ID,
    CLI_SCHEMA_VERSION,
    make_cli_result,
    make_error_report,
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
    from tools.docstring_builder.models import CliResultOptionalFields

    from kgfoundry_common.problem_details import ProblemDetails
else:  # pragma: no cover - runtime stand-in for typing alias
    ProblemDetails = dict[str, object]
    CliResultOptionalFields = dict[str, object]


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


class TestErrorReportConstructor:
    """Test safe construction of ErrorReport with Required/NotRequired fields."""

    def test_make_error_report_with_required_fields(self) -> None:
        """Helper ensures all required fields are set."""
        error = make_error_report(
            file="test.py", status="error", message="Failed to build"
        )

        assert error["file"] == "test.py"
        assert error["status"] == "error"
        assert error["message"] == "Failed to build"
        assert "problem" not in error

    def test_make_error_report_with_optional_problem(self) -> None:
        """Optional problem field can be included."""
        problem = cast(
            "ProblemDetails",
            {
                "type": "https://kgfoundry.dev/problems/internal-error",
                "title": "Internal Error",
                "status": 500,
                "detail": "Failed",
            },
        )
        error = make_error_report(
            file="test.py",
            status="error",
            message="Failed",
            problem=problem,
        )

        assert error.get("problem") == problem


class TestCliResultConstructor:
    """Test safe construction of CliResult with explicit required/optional fields."""

    def test_make_cli_result_minimal(self) -> None:
        """Helper with minimal required fields only."""
        result = make_cli_result(status="success", command="build")

        assert result["schemaVersion"] == CLI_SCHEMA_VERSION
        assert result["schemaId"] == CLI_SCHEMA_ID
        assert result["status"] == "success"
        assert result["command"] == "build"
        assert "generatedAt" in result
        # Optional fields should not be present
        assert "subcommand" not in result

    def test_make_cli_result_with_optionals(self) -> None:
        """Helper includes optional fields when provided."""
        optional: CliResultOptionalFields = {
            "subcommand": "docstrings",
            "durationSeconds": 1.5,
        }
        result = make_cli_result(status="success", command="build", optional=optional)

        assert result["status"] == "success"
        assert result.get("subcommand") == "docstrings"
        assert result.get("durationSeconds") == 1.5

    def test_make_cli_result_datetime_generated(self) -> None:
        """Helper automatically generates current timestamp."""
        result = make_cli_result(status="success", command="build")

        # generatedAt is ISO format string
        assert isinstance(result["generatedAt"], str)
        assert "T" in result["generatedAt"]  # ISO format
        # UTC timezone indicated by +00:00 or Z suffix
        assert result["generatedAt"].endswith(("+00:00", "Z"))


class TestObservabilityIntegration:
    """Test integration with Problem Details and correlation IDs."""

    def test_correlation_context_manager(self) -> None:
        """CorrelationContext sets and clears correlation_id."""
        assert get_correlation_id() is None

        with CorrelationContext("req-123"):
            assert get_correlation_id() == "req-123"
            # Verify with_fields works in context
            with_fields_adapter = with_fields(
                logging.getLogger("test"), correlation_id="req-123"
            )
            assert with_fields_adapter is not None

        assert get_correlation_id() is None
