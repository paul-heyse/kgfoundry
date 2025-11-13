from __future__ import annotations

import importlib
from pathlib import Path
from textwrap import dedent
from typing import Protocol, TypeGuard

import pytest


class _ProblemCarrier(Protocol):
    problem: dict[str, object]


PROBLEM_ATTR = "problem"


def _has_problem_details(exc: BaseException) -> TypeGuard[_ProblemCarrier]:
    problem = getattr(exc, PROBLEM_ATTR, None)
    return isinstance(problem, dict)


facade = importlib.import_module("tools._shared.augment_registry")


def _write_yaml(path: Path, content: str) -> None:
    path.write_text(dedent(content).strip() + "\n", encoding="utf-8")


def test_load_tooling_metadata_success(tmp_path: Path) -> None:
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
    assert override is not None
    assert override.tags == ("cli",)
    interface = metadata.registry.interface("orchestration-cli")
    assert interface is not None
    assert interface.entrypoint == "tests.fixtures.cli:app"
    assert interface.owner == "docs"
    assert interface.operations == {}

    cached_metadata = facade.load_tooling_metadata(
        augment_path=augment_path,
        registry_path=registry_path,
    )
    assert cached_metadata.augment is metadata.augment
    assert cached_metadata.registry is metadata.registry


def test_load_tooling_metadata_missing_augment(tmp_path: Path) -> None:
    registry_path = tmp_path / "registry.yaml"
    _write_yaml(registry_path, "interfaces: {}")

    with pytest.raises(facade.AugmentRegistryError) as excinfo:
        facade.load_tooling_metadata(
            augment_path=tmp_path / "missing.yaml",
            registry_path=registry_path,
        )

    assert _has_problem_details(excinfo.value)
    problem = excinfo.value.problem
    assert problem["status"] == 404
    assert problem["type"] == "https://kgfoundry.dev/problems/augment-registry"


def test_load_tooling_metadata_invalid_registry(tmp_path: Path) -> None:
    augment_path = tmp_path / "augment.yaml"
    registry_path = tmp_path / "registry.yaml"
    _write_yaml(augment_path, "operations: {}")
    _write_yaml(registry_path, "interfaces: null")

    with pytest.raises(facade.AugmentRegistryError) as excinfo:
        facade.load_tooling_metadata(
            augment_path=augment_path,
            registry_path=registry_path,
        )

    assert _has_problem_details(excinfo.value)
    problem = excinfo.value.problem
    assert problem["status"] == 422
    detail = problem.get("detail")
    assert isinstance(detail, str)
    assert "interfaces" in detail


def test_render_problem_details(tmp_path: Path) -> None:
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
    assert "broken" in rendered
