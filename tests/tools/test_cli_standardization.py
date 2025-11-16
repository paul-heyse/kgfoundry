"""Assertions that all CLIs consume the shared cli_tooling contracts consistently."""

from __future__ import annotations

import importlib

import pytest

from tests._helpers import assertions

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

    assertions.expect_equal(settings, module.CLI_SETTINGS)
    assertions.expect_true(module.CLI_CONFIG is config, reason="CLI_CONFIG should be same object")
    assertions.expect_equal(expected_command, module.CLI_COMMAND)
    assertions.expect_equal(expected_title, module.CLI_TITLE)
    assertions.expect_equal(expected_interface, module.CLI_INTERFACE_ID)
    assertions.expect_equal(expected_operation_ids, module.CLI_OPERATION_IDS)

    expected_envelope_dir = context.REPO_ROOT / "site" / "_build" / "cli"
    assertions.expect_equal(expected_envelope_dir, module.CLI_ENVELOPE_DIR)

    if definition is not None:
        assertions.expect_equal(command_name, module.CLI_COMMAND_NAME)
        assertions.expect_equal(
            expected_operation_ids[module.SUBCOMMAND_BUILD_GRAPHS], module.CLI_OPERATION_ID
        )
