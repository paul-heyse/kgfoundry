"""Tests for RFC 9457 problem details helpers used by tooling."""

from __future__ import annotations

import importlib
from dataclasses import dataclass

problem_details = importlib.import_module("tools._shared.problem_details")


def test_coerce_optional_dict_handles_empty_values() -> None:
    helper = problem_details.coerce_optional_dict
    assert helper(None) is None
    assert helper({}) is None
    materialised = helper({"key": "value"})
    assert materialised == {"key": "value"}


@dataclass(slots=True, frozen=True)
class _SchemaError:
    message: str
    absolute_path: tuple[str, ...] = ("root", "field")
    validator: str = "type"


def test_build_schema_problem_details_merges_optional_extensions() -> None:
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

    assert problem["detail"] == "invalid"
    extensions = problem.get("extensions")
    assert isinstance(extensions, dict)
    assert extensions["jsonPointer"] == "/root/field"
    assert extensions["validator"] == "type"
    assert extensions["custom"] == "value"
