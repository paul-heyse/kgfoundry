"""Tests for CLI tooling context loading and configuration."""

from __future__ import annotations

import importlib
from pathlib import Path
from textwrap import dedent
from typing import Protocol, TypeGuard

import pytest

from tests._helpers import assertions

cli_tooling = importlib.import_module("tools._shared.cli_tooling")


class _InterfaceMetaProto(Protocol):
    """Protocol for CLI interface metadata with entrypoint."""

    entrypoint: str


class _CLIConfigProto(Protocol):
    """Protocol for CLI configuration with bin_name and interface metadata."""

    bin_name: str
    interface_meta: _InterfaceMetaProto | None


class _ProblemCarrier(Protocol):
    """Protocol for exceptions that carry Problem Details."""

    problem: dict[str, object]


PROBLEM_ATTR = "problem"


def _is_cli_config(config: object) -> TypeGuard[_CLIConfigProto]:
    """Type guard to check if object matches CLI config protocol.

    Parameters
    ----------
    config : object
        Object to check.

    Returns
    -------
    TypeGuard[_CLIConfigProto]
        True if config has bin_name and interface_meta attributes.
    """
    return hasattr(config, "bin_name") and hasattr(config, "interface_meta")


def _has_problem_details(exc: BaseException) -> TypeGuard[_ProblemCarrier]:
    """Type guard to check if exception carries Problem Details.

    Parameters
    ----------
    exc : BaseException
        Exception to check.

    Returns
    -------
    TypeGuard[_ProblemCarrier]
        True if exception has problem attribute that is a dict.
    """
    problem = getattr(exc, PROBLEM_ATTR, None)
    return isinstance(problem, dict)


def _write_yaml(path: Path, content: str) -> None:
    """Write YAML content to file with dedented formatting.

    Parameters
    ----------
    path : Path
        File path to write to.
    content : str
        YAML content string (may be indented).
    """
    path.write_text(dedent(content).strip() + "\n", encoding="utf-8")


def test_load_cli_tooling_context_success(tmp_path: Path) -> None:
    """Verify CLI tooling context loads successfully with valid configuration."""
    augment_path = tmp_path / "augment.yaml"
    registry_path = tmp_path / "registry.yaml"

    _write_yaml(
        augment_path,
        """
        tags:
          - name: orchestration
            description: Example tag
        operations:
          cli.run:
            tags: [orchestration]
        """,
    )

    _write_yaml(
        registry_path,
        """
        interfaces:
          tools-cli:
            entrypoint: tests.fixtures.cli:app
            binary: kgf
            operations: {}
        """,
    )

    settings = cli_tooling.CLIToolSettings(
        bin_name="kgf",
        title="Test CLI",
        version="1.0.0",
        augment_path=augment_path,
        registry_path=registry_path,
        interface_id="tools-cli",
    )

    context = cli_tooling.load_cli_tooling_context(settings)

    assertions.expect_true(_is_cli_config(context.cli_config), reason="cli_config should be valid")
    cli_config = context.cli_config
    assertions.expect_equal(cli_config.bin_name, "kgf")
    assertions.expect_true(
        cli_config.interface_meta is not None, reason="interface_meta should be set"
    )
    assertions.expect_equal(cli_config.interface_meta.entrypoint, "tests.fixtures.cli:app")
    override = context.augment.operation_override("cli.run")
    assertions.expect_true(override is not None, reason="override should exist")
    assertions.expect_equal(override.tags, ("orchestration",))


def test_load_cli_tooling_context_missing_augment(tmp_path: Path) -> None:
    """Verify loading fails with Problem Details when augment file is missing."""
    registry_path = tmp_path / "registry.yaml"
    _write_yaml(registry_path, "interfaces: {}")

    settings = cli_tooling.CLIToolSettings(
        bin_name="kgf",
        title="Broken CLI",
        version="0.0.1",
        augment_path=tmp_path / "missing.yaml",
        registry_path=registry_path,
    )

    with pytest.raises(cli_tooling.CLIConfigError) as excinfo:
        cli_tooling.load_cli_tooling_context(settings)

    assertions.expect_true(
        _has_problem_details(excinfo.value), reason="should have problem details"
    )
    error = excinfo.value
    if not isinstance(error, cli_tooling.CLIConfigError):  # pragma: no cover - defensive
        pytest.fail("Expected CLIConfigError")
    problem = error.problem
    assertions.expect_equal(problem["status"], 404)
    assertions.expect_equal(problem["type"], "https://kgfoundry.dev/problems/cli-config")


def test_load_cli_tooling_context_missing_interface(tmp_path: Path) -> None:
    """Verify loading fails with Problem Details when interface is missing."""
    augment_path = tmp_path / "augment.yaml"
    registry_path = tmp_path / "registry.yaml"

    _write_yaml(augment_path, "operations: {}")
    _write_yaml(registry_path, "interfaces: {}")

    settings = cli_tooling.CLIToolSettings(
        bin_name="kgf",
        title="Test",
        version="0.0.1",
        augment_path=augment_path,
        registry_path=registry_path,
        interface_id="missing-cli",
    )

    with pytest.raises(cli_tooling.CLIConfigError) as excinfo:
        cli_tooling.load_cli_tooling_context(settings)

    assertions.expect_true(
        _has_problem_details(excinfo.value), reason="should have problem details"
    )
    error = excinfo.value
    if not isinstance(error, cli_tooling.CLIConfigError):  # pragma: no cover - defensive
        pytest.fail("Expected CLIConfigError")
    problem = error.problem
    assertions.expect_equal(problem["status"], 422)
    detail = problem.get("detail")
    assertions.expect_true(isinstance(detail, str), reason="detail should be str")
    assertions.expect_true(
        detail.startswith("Interface 'missing-cli'"),
        reason="detail should mention missing interface",
    )


def test_loaders_use_caching(tmp_path: Path) -> None:
    """Verify loaders cache configuration objects for performance."""
    augment_path = tmp_path / "augment.yaml"
    registry_path = tmp_path / "registry.yaml"

    _write_yaml(augment_path, "operations: {}")
    _write_yaml(registry_path, "interfaces: {}")

    first_augment = cli_tooling.load_augment_config(augment_path)
    second_augment = cli_tooling.load_augment_config(augment_path)
    assertions.expect_true(
        first_augment is second_augment, reason="augment config should be cached"
    )

    first_registry = cli_tooling.load_registry_context(registry_path)
    second_registry = cli_tooling.load_registry_context(registry_path)
    assertions.expect_true(
        first_registry is second_registry, reason="registry context should be cached"
    )
