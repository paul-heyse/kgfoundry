"""Tests for CLI context registry and context loading."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from tools import (
    AugmentMetadataModel,
    CLIToolingContext,
    CLIToolSettings,
    OperationOverrideModel,
    RegistryMetadataModel,
    load_cli_tooling_context,
)
from tools import cli_context_registry as registry_module
from tools.cli_context_registry import (
    CLIContextDefinition,
    context_for,
    default_version_resolver,
    register_cli,
    settings_for,
)

from tests._helpers import assertions


def _unique_key(prefix: str = "test-cli") -> str:
    return f"{prefix}-{uuid4().hex}"


def _default_paths() -> tuple[Path, Path]:
    repo_root = Path(__file__).resolve().parents[2]
    augment_path = repo_root / "openapi" / "_augment_cli.yaml"
    registry_path = repo_root / "tools" / "mkdocs_suite" / "api_registry.yaml"
    return augment_path, registry_path


def _register_test_cli(
    *,
    command: str,
    title: str = "Test CLI",
    interface_id: str | None = None,
    operation_ids: dict[str, str] | None = None,
    packages: Sequence[str] = ("kgfoundry",),
    context_factory: Callable[[CLIToolSettings], CLIToolingContext] | None = None,
) -> str:
    key = command
    augment_path, registry_path = _default_paths()
    definition = CLIContextDefinition(
        command=command,
        title=title,
        interface_id=interface_id or "download-cli",
        operation_ids=operation_ids or {},
        bin_name=command,
        augment_path=augment_path,
        registry_path=registry_path,
        version_resolver=default_version_resolver(*packages),
        context_factory=context_factory,
    )
    register_cli(key, definition)
    return key


def test_settings_for_returns_expected_fields() -> None:
    """Verify settings_for returns expected configuration fields."""
    command = _unique_key()
    key = _register_test_cli(
        command=command,
        operation_ids={"run": "test.run"},
        interface_id="download-cli",
    )

    settings = settings_for(key)

    assertions.expect_equal(settings.bin_name, command)
    assertions.expect_equal(settings.title, "Test CLI")
    assertions.expect_equal(settings.interface_id, "download-cli")
    augment_path, registry_path = _default_paths()
    assertions.expect_equal(settings.augment_path, augment_path)
    assertions.expect_equal(settings.registry_path, registry_path)


def test_context_for_is_cached() -> None:
    """Verify context_for caches contexts to avoid repeated loading."""
    command = _unique_key("cached-cli")
    call_count = {"value": 0}

    def tracking_loader(settings: CLIToolSettings) -> CLIToolingContext:
        call_count["value"] += 1
        return load_cli_tooling_context(settings)

    key = _register_test_cli(command=command, context_factory=tracking_loader)

    ctx_one = context_for(key)
    ctx_two = context_for(key)

    assertions.expect_true(ctx_one is ctx_two, reason="context should be cached")
    assertions.expect_equal(call_count["value"], 1)


def test_duplicate_registration_raises() -> None:
    """Verify duplicate CLI registration raises ValueError."""
    command = _unique_key("duplicate-cli")
    key = _register_test_cli(command=command)
    conflicting = CLIContextDefinition(
        command=command,
        title="Different",
        interface_id="download-cli",
        operation_ids={"run": "conflict"},
        bin_name=command,
    )

    with pytest.raises(ValueError, match="already registered"):
        register_cli(key, conflicting)


def test_unknown_key_raises_key_error() -> None:
    """Verify unknown CLI key raises KeyError."""
    with pytest.raises(KeyError):
        settings_for("unknown-cli")


def test_version_resolver_fallback() -> None:
    """Verify version resolver falls back to available packages."""
    command = _unique_key("version-cli")
    # First package missing, second (kgfoundry) present.
    key = _register_test_cli(command=command, packages=("nonexistent-package", "kgfoundry"))

    settings = settings_for(key)

    assertions.expect_true(settings.version != "0.0.0", reason="version should be resolved")


def test_operation_override_dispatch() -> None:
    """Verify operation override dispatch calls augment correctly."""
    command = _unique_key("override-cli")

    class DummyAugment:
        def __init__(self) -> None:
            self.calls: list[tuple[str, Sequence[str] | None]] = []

        def operation_override(
            self,
            operation_id: str,
            tokens: Sequence[str] | None = None,
        ) -> OperationOverrideModel:
            self.calls.append((operation_id, tokens))
            return OperationOverrideModel(summary="override-result")

    dummy = DummyAugment()

    def context_factory(_settings: CLIToolSettings) -> CLIToolingContext:
        registry = SimpleNamespace(interface=lambda *_args, **_kwargs: None)
        return CLIToolingContext(
            augment=cast("AugmentMetadataModel", dummy),
            registry=cast("RegistryMetadataModel", registry),
            cli_config={},
        )

    key = _register_test_cli(
        command=command,
        operation_ids={"run": "override.run"},
        context_factory=context_factory,
    )

    result = registry_module.operation_override_for(key, subcommand="run")
    assertions.expect_true(isinstance(result, OperationOverrideModel))
    if result is None:  # pragma: no cover - defensive
        pytest.fail("expected OperationOverrideModel")
    assertions.expect_equal(result.summary, "override-result")
    assertions.expect_sequence_equal(dummy.calls, [("override.run", None)])

    assertions.expect_equal(registry_module.operation_override_for(key, subcommand="missing"), None)
