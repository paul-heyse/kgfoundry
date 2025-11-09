"""Tests for ConfigurationError.with_details() and build_configuration_problem()."""

from __future__ import annotations

from inspect import signature
from typing import TYPE_CHECKING, cast

import pytest

from kgfoundry_common.errors import ConfigurationError, ErrorCode
from kgfoundry_common.problem_details import (
    build_configuration_problem,
    render_problem,
    validate_problem_details,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from kgfoundry_common.problem_details import ProblemDetails
    from kgfoundry_common.types import JsonValue
else:  # pragma: no cover - runtime fallbacks for type aliases
    ProblemDetails = dict[str, object]
    JsonValue = object


def _as_problem_dict(problem: ProblemDetails) -> dict[str, object]:
    """Cast problem details to a mutable dictionary for assertions.

    Parameters
    ----------
    problem : ProblemDetails
        Problem details payload.

    Returns
    -------
    dict[str, object]
        Mutable dictionary view.
    """
    return cast("dict[str, object]", problem)


def _as_problem_mapping(problem: ProblemDetails) -> Mapping[str, JsonValue]:
    """Cast problem details to a mapping for schema validation.

    Parameters
    ----------
    problem : ProblemDetails
        Problem details payload.

    Returns
    -------
    Mapping[str, JsonValue]
        Mapping view for validation.
    """
    return cast("Mapping[str, JsonValue]", problem)


class TestConfigurationErrorWithDetails:
    """Test ConfigurationError.with_details() class method."""

    def test_with_details_minimal(self) -> None:
        """Test creating ConfigurationError with field and issue."""
        error = ConfigurationError.with_details(
            field="timeout",
            issue="Must be positive",
        )
        assert isinstance(error, ConfigurationError)
        assert error.code == ErrorCode.CONFIGURATION_ERROR
        assert error.http_status == 500
        assert "timeout" in str(error.context)
        assert "Must be positive" in str(error.context)

    def test_with_details_with_hint(self) -> None:
        """Test creating ConfigurationError with field, issue, and hint."""
        error = ConfigurationError.with_details(
            field="api_key",
            issue="Missing required env var",
            hint="Set KGFOUNDRY_API_KEY before running",
        )
        assert "api_key" in str(error.context)
        assert "Missing required env var" in str(error.context)
        assert "Set KGFOUNDRY_API_KEY before running" in str(error.context)

    def test_with_details_message_format(self) -> None:
        """Test that message is properly formatted with field and issue."""
        error = ConfigurationError.with_details(
            field="port",
            issue="Invalid port number",
        )
        assert "port" in error.message
        assert "Invalid port number" in error.message

    def test_with_details_context_structure(self) -> None:
        """Test that context is properly structured with field, issue, hint."""
        error = ConfigurationError.with_details(
            field="db_host",
            issue="Cannot reach database",
            hint="Check network connectivity",
        )
        assert isinstance(error.context, dict)
        assert error.context["field"] == "db_host"
        assert error.context["issue"] == "Cannot reach database"
        assert error.context["hint"] == "Check network connectivity"

    def test_with_details_no_hint_not_in_context(self) -> None:
        """Test that hint key is not present when hint is None."""
        error = ConfigurationError.with_details(
            field="token",
            issue="Invalid format",
        )
        assert "hint" not in error.context

    def test_with_details_returns_configuration_error(self) -> None:
        """Test that with_details always returns a ConfigurationError instance."""
        error = ConfigurationError.with_details(
            field="name",
            issue="Too long",
            hint="Max 100 chars",
        )
        assert type(error).__name__ == "ConfigurationError"
        assert isinstance(error, ConfigurationError)

    def test_with_details_keyword_only(self) -> None:
        """Test that with_details accepts only keyword parameters."""
        sig = signature(ConfigurationError.with_details)
        for parameter in sig.parameters.values():
            assert parameter.kind.name == "KEYWORD_ONLY"

    def test_with_details_special_characters(self) -> None:
        """Test with_details with special characters in field and issue."""
        error = ConfigurationError.with_details(
            field="server.db.host",
            issue="Invalid IPv4: must be x.x.x.x",
            hint="Use format: 192.168.1.1",
        )
        assert "server.db.host" in str(error.context)
        assert "Invalid IPv4: must be x.x.x.x" in str(error.context)


class TestBuildConfigurationProblem:
    """Test build_configuration_problem() helper function."""

    def test_build_configuration_problem_basic(self) -> None:
        """Test basic Problem Details construction from ConfigurationError."""
        error = ConfigurationError.with_details(
            field="timeout",
            issue="Must be positive",
        )
        problem = build_configuration_problem(error)
        problem_dict = _as_problem_dict(problem)
        assert isinstance(problem, dict)
        assert (
            problem_dict["type"] == "https://kgfoundry.dev/problems/configuration-error"
        )
        assert problem_dict["title"] == "Configuration Error"
        assert problem_dict["status"] == 500
        detail_value = problem_dict.get("detail", "")
        assert "timeout" in str(detail_value)

    def test_build_configuration_problem_with_hint(self) -> None:
        """Test Problem Details includes hint from error context."""
        error = ConfigurationError.with_details(
            field="port",
            issue="Out of valid range",
            hint="Use 1-65535",
        )
        problem = build_configuration_problem(error)
        problem_dict = _as_problem_dict(problem)
        assert "extensions" in problem_dict
        extensions = cast("dict[str, object]", problem_dict["extensions"])
        assert "validation" in extensions
        assert "port" in str(extensions["validation"])
        assert "Use 1-65535" in str(extensions["validation"])

    def test_build_configuration_problem_instance(self) -> None:
        """Test that instance is correctly set."""
        error = ConfigurationError.with_details(
            field="url",
            issue="Invalid protocol",
        )
        problem = build_configuration_problem(error)
        problem_dict = _as_problem_dict(problem)
        assert problem_dict["instance"] == "urn:config:validation"

    def test_build_configuration_problem_code(self) -> None:
        """Test that code is correctly extracted."""
        error = ConfigurationError.with_details(
            field="name",
            issue="Invalid value",
        )
        problem = build_configuration_problem(error)
        problem_dict = _as_problem_dict(problem)
        assert "code" in problem_dict
        assert problem_dict["code"] == "configuration-error"

    def test_build_configuration_problem_extensions(self) -> None:
        """Test that extensions contain exception type and validation details."""
        error = ConfigurationError.with_details(
            field="key",
            issue="Validation failed",
        )
        problem = build_configuration_problem(error)
        problem_dict = _as_problem_dict(problem)
        assert "extensions" in problem_dict
        extensions = cast("dict[str, object]", problem_dict["extensions"])
        assert extensions["exception_type"] == "ConfigurationError"
        assert "validation" in extensions

    def test_build_configuration_problem_rejects_non_config_error(self) -> None:
        """Test that non-ConfigurationError raises TypeError."""
        regular_error = ValueError("some error")
        with pytest.raises(TypeError, match="expected ConfigurationError"):
            build_configuration_problem(regular_error)

    def test_build_configuration_problem_validates_against_schema(self) -> None:
        """Test that generated Problem Details validates against schema."""
        error = ConfigurationError.with_details(
            field="data",
            issue="Schema validation failed",
        )
        problem = build_configuration_problem(error)
        validate_problem_details(_as_problem_mapping(problem))

    def test_build_configuration_problem_multiple_fields(self) -> None:
        """Test Problem Details with multi-field error context."""
        error = ConfigurationError(
            "Multiple validation errors",
            context={
                "field_1": {"issue": "Too short"},
                "field_2": {"issue": "Invalid format"},
            },
        )
        problem = build_configuration_problem(error)
        problem_dict = _as_problem_dict(problem)
        extensions = cast("dict[str, object]", problem_dict.get("extensions", {}))
        assert "validation" in extensions
        validation_ctx = cast("dict[str, object]", extensions.get("validation"))
        assert "field_1" in str(validation_ctx)
        assert "field_2" in str(validation_ctx)

    def test_build_configuration_problem_preserves_error_message(self) -> None:
        """Test that error message is preserved in detail."""
        error = ConfigurationError.with_details(
            field="email",
            issue="Invalid email format",
            hint="Use user@domain.com",
        )
        problem = build_configuration_problem(error)
        problem_dict = _as_problem_dict(problem)
        # The detail should contain info about the field
        detail_value = problem_dict.get("detail", "")
        assert "email" in str(detail_value) or "email" in str(problem_dict)

    def test_build_configuration_problem_http_status_code(self) -> None:
        """Test that HTTP status is 500 for configuration errors."""
        error = ConfigurationError.with_details(
            field="retry_count",
            issue="Must be non-negative",
        )
        problem = build_configuration_problem(error)
        problem_dict = _as_problem_dict(problem)
        assert problem_dict["status"] == 500


class TestConfigurationErrorIntegration:
    """Integration tests for ConfigurationError and Problem Details."""

    def test_problem_details_render(self) -> None:
        """Test that Problem Details can be rendered to JSON."""
        error = ConfigurationError.with_details(
            field="setting",
            issue="Invalid configuration",
        )
        problem = build_configuration_problem(error)
        json_str = render_problem(problem)
        assert isinstance(json_str, str)
        assert "configuration-error" in json_str
        assert "setting" in json_str

    def test_error_with_cause_chain(self) -> None:
        """Test ConfigurationError preserves cause chain."""
        original_error = ValueError("Invalid value")
        error = ConfigurationError(
            "Configuration failed",
            cause=original_error,
            context={"field": "value", "issue": "Validation"},
        )
        assert error.__cause__ is original_error
        problem = build_configuration_problem(error)
        problem_dict = _as_problem_dict(problem)
        extensions = cast("dict[str, object]", problem_dict.get("extensions", {}))
        assert "validation" in extensions

    def test_multiple_configuration_errors_as_problems(self) -> None:
        """Test creating multiple Problem Details from different errors."""
        errors = [
            ConfigurationError.with_details(field="f1", issue="i1"),
            ConfigurationError.with_details(field="f2", issue="i2"),
            ConfigurationError.with_details(field="f3", issue="i3"),
        ]
        problems = [build_configuration_problem(e) for e in errors]
        assert len(problems) == 3
        for problem in problems:
            problem_dict = _as_problem_dict(problem)
            assert (
                problem_dict["type"]
                == "https://kgfoundry.dev/problems/configuration-error"
            )
            assert problem_dict["status"] == 500
