"""Tests for augment registry loading and validation."""

from __future__ import annotations

import importlib
from pathlib import Path
from textwrap import dedent
from typing import Protocol, TypeGuard

import pytest

from tests._helpers import assertions


class _ProblemCarrier(Protocol):
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


facade = importlib.import_module("tools._shared.augment_registry")


def _write_yaml(path: Path, content: str) -> None:
    path.write_text(dedent(content).strip() + "\n", encoding="utf-8")


def test_load_tooling_metadata_success(tmp_path: Path) -> None:
    """Verify loading tooling metadata succeeds with valid files."""
    augment_path = tmp_path / "augment.yaml"
    registry_path = tmp_path / "registry.yaml"

    _write_yaml(
        augment_path,
        """
        operations:
          cli.run:
            tags: [cli]
        x-tagGroups:
          - name: CLI Commands
            tags: [cli]
        """,
    )

    _write_yaml(
        registry_path,
        """
        interfaces:
          orchestration-cli:
            entrypoint: tests.fixtures.cli:app
            owner: docs
            operations: {}
        """,
    )

    metadata = facade.load_tooling_metadata(
        augment_path=augment_path,
        registry_path=registry_path,
    )

    override = metadata.augment.operation_override("cli.run")
    assertions.expect_true(override is not None, reason="override should exist")
    assertions.expect_equal(override.tags, ("cli",))
    interface = metadata.registry.interface("orchestration-cli")
    assertions.expect_true(interface is not None, reason="interface should exist")
    assertions.expect_equal(interface.entrypoint, "tests.fixtures.cli:app")
    assertions.expect_equal(interface.owner, "docs")
    assertions.expect_equal(interface.operations, {})

    cached_metadata = facade.load_tooling_metadata(
        augment_path=augment_path,
        registry_path=registry_path,
    )
    assertions.expect_true(
        cached_metadata.augment is metadata.augment, reason="augment should be cached"
    )
    assertions.expect_true(
        cached_metadata.registry is metadata.registry, reason="registry should be cached"
    )


def test_load_tooling_metadata_missing_augment(tmp_path: Path) -> None:
    """Verify loading fails with Problem Details when augment file is missing."""
    registry_path = tmp_path / "registry.yaml"
    _write_yaml(registry_path, "interfaces: {}")

    with pytest.raises(facade.AugmentRegistryError) as excinfo:
        facade.load_tooling_metadata(
            augment_path=tmp_path / "missing.yaml",
            registry_path=registry_path,
        )

    assertions.expect_true(
        _has_problem_details(excinfo.value), reason="should have problem details"
    )
    problem = excinfo.value.problem
    assertions.expect_equal(problem["status"], 404)
    assertions.expect_equal(problem["type"], "https://kgfoundry.dev/problems/augment-registry")


def test_load_tooling_metadata_invalid_registry(tmp_path: Path) -> None:
    """Verify loading fails with Problem Details when registry is invalid."""
    augment_path = tmp_path / "augment.yaml"
    registry_path = tmp_path / "registry.yaml"
    _write_yaml(augment_path, "operations: {}")
    _write_yaml(registry_path, "interfaces: null")

    with pytest.raises(facade.AugmentRegistryError) as excinfo:
        facade.load_tooling_metadata(
            augment_path=augment_path,
            registry_path=registry_path,
        )

    assertions.expect_true(
        _has_problem_details(excinfo.value), reason="should have problem details"
    )
    problem = excinfo.value.problem
    assertions.expect_equal(problem["status"], 422)
    detail = problem.get("detail")
    assertions.expect_true(isinstance(detail, str), reason="detail should be str")
    assertions.expect_in("interfaces", detail)


def test_render_problem_details(tmp_path: Path) -> None:
    """Verify Problem Details rendering includes error detail."""
    registry_path = tmp_path / "registry.yaml"
    _write_yaml(registry_path, "interfaces: {}")

    error = facade.AugmentRegistryError(
        {
            "type": "https://kgfoundry.dev/problems/augment-registry",
            "title": "failure",
            "status": 500,
            "detail": "broken",
            "instance": "urn:test",
        }
    )
    rendered = facade.render_problem_details(error)
    assertions.expect_in("broken", rendered)
