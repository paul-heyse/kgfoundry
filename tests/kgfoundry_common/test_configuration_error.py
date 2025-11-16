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
from tests._helpers import assertions

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


def test_with_details_minimal() -> None:
    """Test creating ConfigurationError with field and issue."""
    error = ConfigurationError.with_details(
        field="timeout",
        issue="Must be positive",
    )
    assertions.expect_true(
        isinstance(error, ConfigurationError), reason="should be ConfigurationError"
    )
    assertions.expect_equal(error.code, ErrorCode.CONFIGURATION_ERROR)
    assertions.expect_equal(error.http_status, 500)
    assertions.expect_true("timeout" in str(error.context), reason="context should contain timeout")
    assertions.expect_true(
        "Must be positive" in str(error.context), reason="context should contain issue"
    )


def test_with_details_with_hint() -> None:
    """Test creating ConfigurationError with field, issue, and hint."""
    error = ConfigurationError.with_details(
        field="api_key",
        issue="Missing required env var",
        hint="Set KGFOUNDRY_API_KEY before running",
    )
    assertions.expect_true("api_key" in str(error.context), reason="context should contain api_key")
    assertions.expect_true(
        "Missing required env var" in str(error.context), reason="context should contain issue"
    )
    assertions.expect_true(
        "Set KGFOUNDRY_API_KEY before running" in str(error.context),
        reason="context should contain hint",
    )


def test_with_details_message_format() -> None:
    """Test that message is properly formatted with field and issue."""
    error = ConfigurationError.with_details(
        field="port",
        issue="Invalid port number",
    )
    assertions.expect_true("port" in error.message, reason="message should contain port")
    assertions.expect_true(
        "Invalid port number" in error.message, reason="message should contain issue"
    )


def test_with_details_context_structure() -> None:
    """Test that context is properly structured with field, issue, hint."""
    error = ConfigurationError.with_details(
        field="db_host",
        issue="Cannot reach database",
        hint="Check network connectivity",
    )
    assertions.expect_true(isinstance(error.context, dict), reason="context should be dict")
    assertions.expect_equal(error.context["field"], "db_host")
    assertions.expect_equal(error.context["issue"], "Cannot reach database")
    assertions.expect_equal(error.context["hint"], "Check network connectivity")


def test_with_details_no_hint_not_in_context() -> None:
    """Test that hint key is not present when hint is None."""
    error = ConfigurationError.with_details(
        field="token",
        issue="Invalid format",
    )
    assertions.expect_false(
        "hint" in error.context, reason="hint should not be in context when None"
    )


def test_with_details_returns_configuration_error() -> None:
    """Test that with_details always returns a ConfigurationError instance."""
    error = ConfigurationError.with_details(
        field="name",
        issue="Too long",
        hint="Max 100 chars",
    )
    assertions.expect_equal(type(error).__name__, "ConfigurationError")
    assertions.expect_true(
        isinstance(error, ConfigurationError), reason="should be ConfigurationError"
    )


def test_with_details_keyword_only() -> None:
    """Test that with_details accepts only keyword parameters."""
    sig = signature(ConfigurationError.with_details)
    for parameter in sig.parameters.values():
        assertions.expect_equal(parameter.kind.name, "KEYWORD_ONLY")


def test_with_details_special_characters() -> None:
    """Test with_details with special characters in field and issue."""
    error = ConfigurationError.with_details(
        field="server.db.host",
        issue="Invalid IPv4: must be x.x.x.x",
        hint="Use format: 192.168.1.1",
    )
    assertions.expect_true(
        "server.db.host" in str(error.context), reason="context should contain field"
    )
    assertions.expect_true(
        "Invalid IPv4: must be x.x.x.x" in str(error.context),
        reason="context should contain issue",
    )


def test_build_configuration_problem_basic() -> None:
    """Test basic Problem Details construction from ConfigurationError."""
    error = ConfigurationError.with_details(
        field="timeout",
        issue="Must be positive",
    )
    problem = build_configuration_problem(error)
    problem_dict = _as_problem_dict(problem)
    assertions.expect_true(isinstance(problem, dict), reason="problem should be dict")
    assertions.expect_equal(
        problem_dict["type"], "https://kgfoundry.dev/problems/configuration-error"
    )
    assertions.expect_equal(problem_dict["title"], "Configuration Error")
    assertions.expect_equal(problem_dict["status"], 500)
    detail_value = problem_dict.get("detail", "")
    assertions.expect_true("timeout" in str(detail_value), reason="detail should contain timeout")


def test_build_configuration_problem_with_hint() -> None:
    """Test Problem Details includes hint from error context."""
    error = ConfigurationError.with_details(
        field="port",
        issue="Out of valid range",
        hint="Use 1-65535",
    )
    problem = build_configuration_problem(error)
    problem_dict = _as_problem_dict(problem)
    assertions.expect_true("extensions" in problem_dict, reason="problem should have extensions")
    extensions = cast("dict[str, object]", problem_dict["extensions"])
    assertions.expect_true("validation" in extensions, reason="extensions should have validation")
    assertions.expect_true(
        "port" in str(extensions["validation"]), reason="validation should contain port"
    )
    assertions.expect_true(
        "Use 1-65535" in str(extensions["validation"]), reason="validation should contain hint"
    )


def test_build_configuration_problem_instance() -> None:
    """Test that instance is correctly set."""
    error = ConfigurationError.with_details(
        field="url",
        issue="Invalid protocol",
    )
    problem = build_configuration_problem(error)
    problem_dict = _as_problem_dict(problem)
    assertions.expect_equal(problem_dict["instance"], "urn:config:validation")


def test_build_configuration_problem_code() -> None:
    """Test that code is correctly extracted."""
    error = ConfigurationError.with_details(
        field="name",
        issue="Invalid value",
    )
    problem = build_configuration_problem(error)
    problem_dict = _as_problem_dict(problem)
    assertions.expect_true("code" in problem_dict, reason="problem should have code")
    assertions.expect_equal(problem_dict["code"], "configuration-error")


def test_build_configuration_problem_extensions() -> None:
    """Test that extensions contain exception type and validation details."""
    error = ConfigurationError.with_details(
        field="key",
        issue="Validation failed",
    )
    problem = build_configuration_problem(error)
    problem_dict = _as_problem_dict(problem)
    assertions.expect_true("extensions" in problem_dict, reason="problem should have extensions")
    extensions = cast("dict[str, object]", problem_dict["extensions"])
    assertions.expect_equal(extensions["exception_type"], "ConfigurationError")
    assertions.expect_true("validation" in extensions, reason="extensions should have validation")


def test_build_configuration_problem_rejects_non_config_error() -> None:
    """Test that non-ConfigurationError raises TypeError."""
    regular_error = ValueError("some error")
    with pytest.raises(TypeError, match="expected ConfigurationError"):
        build_configuration_problem(regular_error)


def test_build_configuration_problem_validates_against_schema() -> None:
    """Test that generated Problem Details validates against schema."""
    error = ConfigurationError.with_details(
        field="data",
        issue="Schema validation failed",
    )
    problem = build_configuration_problem(error)
    validate_problem_details(_as_problem_mapping(problem))


def test_build_configuration_problem_multiple_fields() -> None:
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
    assertions.expect_true("validation" in extensions, reason="extensions should have validation")
    validation_ctx = cast("dict[str, object]", extensions.get("validation"))
    assertions.expect_true(
        "field_1" in str(validation_ctx), reason="validation should contain field_1"
    )
    assertions.expect_true(
        "field_2" in str(validation_ctx), reason="validation should contain field_2"
    )


def test_build_configuration_problem_preserves_error_message() -> None:
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
    assertions.expect_true(
        "email" in str(detail_value) or "email" in str(problem_dict),
        reason="problem should contain email",
    )


def test_build_configuration_problem_http_status_code() -> None:
    """Test that HTTP status is 500 for configuration errors."""
    error = ConfigurationError.with_details(
        field="retry_count",
        issue="Must be non-negative",
    )
    problem = build_configuration_problem(error)
    problem_dict = _as_problem_dict(problem)
    assertions.expect_equal(problem_dict["status"], 500)


def test_problem_details_render() -> None:
    """Test that Problem Details can be rendered to JSON."""
    error = ConfigurationError.with_details(
        field="setting",
        issue="Invalid configuration",
    )
    problem = build_configuration_problem(error)
    json_str = render_problem(problem)
    assertions.expect_true(isinstance(json_str, str), reason="render_problem should return str")
    assertions.expect_true(
        "configuration-error" in json_str, reason="json should contain error type"
    )
    assertions.expect_true("setting" in json_str, reason="json should contain field")


def test_error_with_cause_chain() -> None:
    """Test ConfigurationError preserves cause chain."""
    original_error = ValueError("Invalid value")
    error = ConfigurationError(
        "Configuration failed",
        cause=original_error,
        context={"field": "value", "issue": "Validation"},
    )
    assertions.expect_true(error.__cause__ is original_error, reason="error should preserve cause")
    problem = build_configuration_problem(error)
    problem_dict = _as_problem_dict(problem)
    extensions = cast("dict[str, object]", problem_dict.get("extensions", {}))
    assertions.expect_true("validation" in extensions, reason="extensions should have validation")


def test_multiple_configuration_errors_as_problems() -> None:
    """Test creating multiple Problem Details from different errors."""
    errors = [
        ConfigurationError.with_details(field="f1", issue="i1"),
        ConfigurationError.with_details(field="f2", issue="i2"),
        ConfigurationError.with_details(field="f3", issue="i3"),
    ]
    problems = [build_configuration_problem(e) for e in errors]
    assertions.expect_equal(len(problems), 3)
    for problem in problems:
        problem_dict = _as_problem_dict(problem)
        assertions.expect_equal(
            problem_dict["type"], "https://kgfoundry.dev/problems/configuration-error"
        )
        assertions.expect_equal(problem_dict["status"], 500)
