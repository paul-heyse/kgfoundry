"""Assertions that all CLIs consume the shared cli_tooling contracts consistently."""

from __future__ import annotations

import importlib

import pytest

CLI_SUITES = (
    ("download.cli", "download.cli_context", None),
    ("orchestration.cli", "orchestration.cli_context", None),
)


@pytest.mark.parametrize(("module_path", "context_path", "command_name"), list(CLI_SUITES))
def test_cli_configuration_matches_context(
    module_path: str, context_path: str, command_name: str | None
) -> None:
    """Ensure each CLI module mirrors the metadata provided by its cli_context."""
    module = importlib.import_module(module_path)
    context = importlib.import_module(context_path)

    if command_name is not None:
        definition = context.get_cli_definition(command_name)
        settings = context.get_cli_settings(command_name)
        config = context.get_cli_config(command_name)
        expected_command = definition.command
        expected_title = definition.title
        expected_interface = definition.interface_id
        expected_operation_ids = dict(definition.operation_ids)
    else:
        definition = None
        settings = context.get_cli_settings()
        config = context.get_cli_config()
        expected_command = context.CLI_COMMAND
        expected_title = context.CLI_TITLE
        expected_interface = context.CLI_INTERFACE_ID
        expected_operation_ids = dict(context.CLI_OPERATION_IDS)

    assert settings == module.CLI_SETTINGS
    assert module.CLI_CONFIG is config
    assert expected_command == module.CLI_COMMAND
    assert expected_title == module.CLI_TITLE
    assert expected_interface == module.CLI_INTERFACE_ID
    assert expected_operation_ids == module.CLI_OPERATION_IDS

    expected_envelope_dir = context.REPO_ROOT / "site" / "_build" / "cli"
    assert expected_envelope_dir == module.CLI_ENVELOPE_DIR

    if definition is not None:
        assert command_name == module.CLI_COMMAND_NAME
        assert expected_operation_ids[module.SUBCOMMAND_BUILD_GRAPHS] == module.CLI_OPERATION_ID
