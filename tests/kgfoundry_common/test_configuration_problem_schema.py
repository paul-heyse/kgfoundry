"""Tests for ConfigurationError Problem Details schema validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

from kgfoundry_common.errors import ConfigurationError
from kgfoundry_common.problem_details import (
    build_configuration_problem,
    validate_problem_details,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from kgfoundry_common.problem_details import ProblemDetails
    from kgfoundry_common.types import JsonValue
else:  # pragma: no cover - runtime stand-ins for type aliases
    ProblemDetails = dict[str, object]
    JsonValue = object


def _load_sample_payload() -> dict[str, JsonValue]:
    """Load the sample payload JSON file.

    Returns
    -------
    dict[str, JsonValue]
        Parsed JSON payload.
    """
    sample_path = (
        Path(__file__).parent.parent.parent
        / "schema"
        / "examples"
        / "problem_details"
        / "public-api-invalid-config.json"
    )
    with Path(sample_path).open(encoding="utf-8") as f:
        return cast("dict[str, JsonValue]", json.load(f))


def _as_problem_dict(problem: ProblemDetails) -> dict[str, object]:
    """Return a mutable dictionary view of the problem details payload.

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
    """Return a mapping view for schema validation assertions.

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


class TestConfigurationProblemSchema:
    """Test schema validation for configuration error Problem Details."""

    def test_sample_payload_exists(self) -> None:
        """Test that the sample payload file exists."""
        sample_path = (
            Path(__file__).parent.parent.parent
            / "schema"
            / "examples"
            / "problem_details"
            / "public-api-invalid-config.json"
        )
        assert sample_path.exists(), f"Sample payload not found at {sample_path}"

    def test_sample_payload_is_valid_json(self) -> None:
        """Test that the sample payload is valid JSON."""
        payload = _load_sample_payload()
        assert isinstance(payload, dict)

    def test_sample_payload_validates_against_schema(self) -> None:
        """Test that the sample payload validates against the schema."""
        payload = _load_sample_payload()
        validate_problem_details(cast("Mapping[str, JsonValue]", payload))

    def test_sample_payload_has_required_fields(self) -> None:
        """Test that sample payload contains all required Problem Details fields."""
        payload = _load_sample_payload()

        required_fields = ["type", "title", "status", "detail", "instance"]
        for field in required_fields:
            assert field in payload, f"Required field '{field}' missing from sample"

    def test_sample_payload_has_configuration_error_type(self) -> None:
        """Test that sample uses configuration-error problem type."""
        payload = _load_sample_payload()

        assert payload["type"] == "https://kgfoundry.dev/problems/configuration-error"
        assert payload["code"] == "configuration-error"

    def test_sample_payload_has_validation_context(self) -> None:
        """Test that sample contains validation context with field, issue, and hint."""
        payload = _load_sample_payload()

        assert "extensions" in payload
        extensions = cast("dict[str, object]", payload["extensions"])
        assert "validation" in extensions
        validation = cast("dict[str, object]", extensions["validation"])
        assert "field" in validation
        assert "issue" in validation
        assert "hint" in validation

    def test_generated_problem_matches_sample_structure(self) -> None:
        """Test that generated Problem Details matches sample structure."""
        error = ConfigurationError.with_details(
            field="timeout_seconds",
            issue="Must be > 0",
            hint="Provide a positive integer value for timeout in seconds",
        )
        problem = build_configuration_problem(error)
        problem_dict = _as_problem_dict(problem)

        # Verify structure matches sample
        assert problem_dict["type"] == "https://kgfoundry.dev/problems/configuration-error"
        assert problem_dict["title"] == "Configuration Error"
        assert problem_dict["status"] == 500
        assert problem_dict["instance"] == "urn:config:validation"
        assert problem_dict["code"] == "configuration-error"
        assert "extensions" in problem_dict


class TestConfigurationProblemSchemaParity:
    """Test that generated problems maintain schema parity."""

    def test_all_generated_problems_validate_against_schema(self) -> None:
        """Test that all generated configuration problems pass schema validation."""
        test_cases: list[tuple[str, str, str | None]] = [
            ("timeout", "Must be positive", None),
            ("api_key", "Missing required env var", "Set KGFOUNDRY_API_KEY"),
            ("port", "Out of valid range", "Use 1-65535"),
            ("db_host", "Cannot connect", None),
        ]

        for field, issue, hint in test_cases:
            error = ConfigurationError.with_details(
                field=field,
                issue=issue,
                hint=hint,
            )
            problem = build_configuration_problem(error)
            validate_problem_details(_as_problem_mapping(problem))

    def test_sample_and_generated_both_have_extensions(self) -> None:
        """Test that both sample and generated problems use extensions field."""
        sample = _load_sample_payload()

        error = ConfigurationError.with_details(
            field="test",
            issue="Test issue",
        )
        generated = build_configuration_problem(error)
        generated_dict = _as_problem_dict(generated)

        assert "extensions" in sample
        assert "extensions" in generated_dict

    def test_sample_http_status_is_500(self) -> None:
        """Test that sample payload has HTTP 500 status for config errors."""
        payload = _load_sample_payload()
        assert payload["status"] == 500

    def test_generated_problem_instance_is_urn(self) -> None:
        """Test that generated problems use urn: for instance."""
        error = ConfigurationError.with_details(
            field="test",
            issue="Test issue",
        )
        problem = build_configuration_problem(error)
        problem_dict = _as_problem_dict(problem)

        instance = problem_dict.get("instance", "")
        assert str(instance).startswith("urn:")


class TestConfigurationProblemDocumentation:
    """Test that Problem Details are properly documented."""

    def test_sample_payload_contains_field_name(self) -> None:
        """Test that sample payload documents the field name for error context."""
        payload = _load_sample_payload()

        extensions = cast("dict[str, object]", payload["extensions"])
        validation = cast("dict[str, object]", extensions["validation"])
        assert validation["field"] == "timeout_seconds"

    def test_sample_payload_contains_readable_issue_description(self) -> None:
        """Test that sample payload has human-readable issue description."""
        payload = _load_sample_payload()

        extensions = cast("dict[str, object]", payload["extensions"])
        validation = cast("dict[str, object]", extensions["validation"])
        assert len(cast("str", validation["issue"])) > 0
        assert validation["issue"] == "Must be > 0"

    def test_sample_payload_contains_resolution_hint(self) -> None:
        """Test that sample payload includes a hint for resolving the issue."""
        payload = _load_sample_payload()

        extensions = cast("dict[str, object]", payload["extensions"])
        validation = cast("dict[str, object]", extensions["validation"])
        assert "hint" in validation
        assert len(cast("str", validation["hint"])) > 0
