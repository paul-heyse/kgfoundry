"""Tests for RFC 9457 problem details helpers used by tooling."""

from __future__ import annotations

import importlib
from dataclasses import dataclass

from tests._helpers import assertions

problem_details = importlib.import_module("tools._shared.problem_details")


def test_coerce_optional_dict_handles_empty_values() -> None:
    """Test that coerce_optional_dict returns None for empty inputs.

    Extended Summary
    ----------------
    Verifies that the helper function correctly handles None and empty dict
    inputs by returning None, while preserving non-empty dictionaries.
    """
    helper = problem_details.coerce_optional_dict
    assertions.expect_equal(helper(None), None)
    assertions.expect_equal(helper({}), None)
    materialised = helper({"key": "value"})
    assertions.expect_equal(materialised, {"key": "value"})


@dataclass(slots=True, frozen=True)
class _SchemaError:
    """Test dataclass representing a schema validation error."""

    message: str
    absolute_path: tuple[str, ...] = ("root", "field")
    validator: str = "type"


def test_build_schema_problem_details_merges_optional_extensions() -> None:
    """Test that schema problem details merge base and extension fields.

    Extended Summary
    ----------------
    Verifies that build_schema_problem_details correctly merges base problem
    details parameters with schema-specific error information and custom
    extension fields, ensuring all fields appear in the final problem details
    structure.
    """
    base = problem_details.ProblemDetailsParams(
        type="https://kgfoundry.dev/problems/test",
        title="Test",
        status=400,
        detail="",
        instance="urn:test:example",
    )
    params = problem_details.SchemaProblemDetailsParams(
        base=base,
        error=_SchemaError("invalid"),
        extensions={"custom": "value"},
    )

    problem = problem_details.build_schema_problem_details(params)

    assertions.expect_equal(problem["detail"], "invalid")
    extensions = problem.get("extensions")
    assertions.expect_true(isinstance(extensions, dict), reason="extensions should be dict")
    if isinstance(extensions, dict):
        assertions.expect_equal(extensions["jsonPointer"], "/root/field")
        assertions.expect_equal(extensions["validator"], "type")
        assertions.expect_equal(extensions["custom"], "value")
