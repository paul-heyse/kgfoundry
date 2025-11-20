"""Tests for CLI metadata models and validation."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Protocol, TypeGuard, cast

import pytest

from tests._helpers import assertions

augment_registry = importlib.import_module("tools._shared.augment_registry")


class _ProblemCarrier(Protocol):
    """Protocol for exceptions that carry Problem Details."""

    problem: dict[str, object]


PROBLEM_ATTR = "problem"


def _has_problem_details(exc: BaseException) -> TypeGuard[_ProblemCarrier]:
    """Check if exception has Problem Details attribute.

    Parameters
    ----------
    exc : BaseException
        Exception to check.

    Returns
    -------
    TypeGuard[_ProblemCarrier]
        True if exception has problem attribute.
    """
    problem = getattr(exc, PROBLEM_ATTR, None)
    return isinstance(problem, dict)


def test_augment_metadata_model_normalises_sequences() -> None:
    """Verify AugmentMetadataModel normalizes sequences and removes duplicates."""
    model = augment_registry.AugmentMetadataModel.model_validate(
        {
            "path": Path("augment.yaml"),
            "payload": {
                "operations": {
                    "cli.run": {
                        "tags": ["cli", "admin", "cli"],
                        "x-handler": "tests.cli:run",
                        "x-env": ["KGF_ENV"],
                        "examples": ["kgf run"],
                        "x-codeSamples": [
                            {"lang": "bash", "source": "kgf run"},
                        ],
                    }
                },
                "x-tagGroups": [
                    {"name": "Commands", "tags": ["cli", "admin", "cli"]},
                ],
            },
        }
    )

    override = model.operation_override("cli.run")
    assertions.expect_true(override is not None, reason="override should exist")
    assertions.expect_sequence_equal(list(override.tags), ["cli", "admin"])
    assertions.expect_sequence_equal(list(override.env), ["KGF_ENV"])
    assertions.expect_sequence_equal(list(override.examples), ["kgf run"])
    payload = model.payload
    assertions.expect_true(isinstance(payload, dict), reason="payload should be dict")
    operations = payload.get("operations")
    assertions.expect_true(isinstance(operations, dict), reason="operations should be dict")
    cli_run = operations.get("cli.run")
    assertions.expect_true(isinstance(cli_run, dict), reason="cli.run should be dict")
    assertions.expect_sequence_equal(cast("list[str]", cli_run.get("x-env")), ["KGF_ENV"])
    assertions.expect_sequence_equal(list(model.tag_groups[0].tags), ["cli", "admin"])


def test_registry_metadata_model_validates_interfaces() -> None:
    """Verify RegistryMetadataModel validates interface definitions."""
    model = augment_registry.RegistryMetadataModel.model_validate(
        {
            "path": Path("registry.yaml"),
            "interfaces": {
                "tools-cli": {
                    "entrypoint": "tests.cli:app",
                    "owner": "docs",
                    "operations": {
                        "run": {
                            "operation_id": "cli.run",
                            "handler": "tests.cli:run",
                            "tags": ["cli"],
                        }
                    },
                }
            },
        }
    )

    interface = model.interface("tools-cli")
    assertions.expect_true(interface is not None, reason="interface should exist")
    assertions.expect_equal(interface.entrypoint, "tests.cli:app")
    assertions.expect_equal(interface.operations["run"].handler, "tests.cli:run")


def test_load_augment_reports_validation_errors(tmp_path: Path) -> None:
    """Verify load_augment reports validation errors with Problem Details."""
    augment_path = tmp_path / "augment.yaml"
    augment_path.write_text(
        """
        operations:
          cli.run:
            tags: invalid  # not a sequence
        """,
        encoding="utf-8",
    )

    with pytest.raises(augment_registry.AugmentRegistryValidationError) as excinfo:
        augment_registry.load_augment(augment_path)

    assertions.expect_true(
        _has_problem_details(excinfo.value), reason="should have problem details"
    )
    error = excinfo.value
    if not isinstance(error, augment_registry.AugmentRegistryValidationError):  # pragma: no cover
        pytest.fail("Expected AugmentRegistryValidationError")
    problem = error.problem
    assertions.expect_equal(problem["status"], 422)
    errors = problem.get("errors")
    assertions.expect_true(isinstance(errors, list), reason="errors should be a list")
    assertions.expect_true(
        any(
            isinstance(error, dict) and "tags" in str(error.get("loc", ""))
            for error in cast("list[dict[str, object]]", errors)
        ),
        reason="should have tags error",
    )
