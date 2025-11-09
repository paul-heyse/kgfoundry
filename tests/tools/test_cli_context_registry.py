from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from tools import CLIToolingContext
from tools import cli_context_registry as registry_module
from tools._shared.augment_registry import AugmentMetadataModel
from tools.cli_context_registry import (
    CLIContextDefinition,
    context_for,
    default_version_resolver,
    register_cli,
    settings_for,
)


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
    )
    register_cli(key, definition)
    return key


def test_settings_for_returns_expected_fields() -> None:
    command = _unique_key()
    key = _register_test_cli(
        command=command,
        operation_ids={"run": "test.run"},
        interface_id="download-cli",
    )

    settings = settings_for(key)

    assert settings.bin_name == command
    assert settings.title == "Test CLI"
    assert settings.interface_id == "download-cli"
    augment_path, registry_path = _default_paths()
    assert settings.augment_path == augment_path
    assert settings.registry_path == registry_path


def test_context_for_is_cached() -> None:
    command = _unique_key("cached-cli")
    key = _register_test_cli(command=command)

    shared_registry = sys.modules["tools._shared.cli_context_registry"]
    original_loader = shared_registry.load_cli_tooling_context
    call_count = {"value": 0}

    def _fake_loader(*args: object, **kwargs: object) -> CLIToolingContext:
        call_count["value"] += 1
        return original_loader(*args, **kwargs)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(shared_registry, "load_cli_tooling_context", _fake_loader)

    ctx_one = context_for(key)
    ctx_two = context_for(key)

    assert ctx_one is ctx_two
    assert call_count["value"] == 1
    monkeypatch.undo()


def test_duplicate_registration_raises() -> None:
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
    with pytest.raises(KeyError):
        settings_for("unknown-cli")


def test_version_resolver_fallback() -> None:
    command = _unique_key("version-cli")
    # First package missing, second (kgfoundry) present.
    key = _register_test_cli(command=command, packages=("nonexistent-package", "kgfoundry"))

    settings = settings_for(key)

    assert settings.version != "0.0.0"


def test_operation_override_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    command = _unique_key("override-cli")
    key = _register_test_cli(command=command, operation_ids={"run": "override.run"})

    class DummyAugment:
        def __init__(self) -> None:
            self.calls: list[tuple[str, Sequence[str] | None]] = []

        def operation_override(
            self,
            operation_id: str,
            tokens: Sequence[str] | None = None,
        ) -> str:
            self.calls.append((operation_id, tokens))
            return "override-result"

    dummy = DummyAugment()
    original_augment_for = registry_module.REGISTRY.augment_for

    def fake_augment_for(target: str) -> AugmentMetadataModel:
        if target == key:
            return cast("AugmentMetadataModel", dummy)
        return original_augment_for(target)

    monkeypatch.setattr(registry_module.REGISTRY, "augment_for", fake_augment_for)

    result = registry_module.operation_override_for(key, subcommand="run")
    assert result == "override-result"
    assert dummy.calls == [("override.run", None)]

    assert registry_module.operation_override_for(key, subcommand="missing") is None
