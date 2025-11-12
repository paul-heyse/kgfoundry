"""Tests for CLI context module helpers.

This module verifies that CLI context helpers work correctly for registered
CLI modules, including download, orchestration, and optional codeintel modules.
"""

from __future__ import annotations

import importlib
from typing import Any, cast

import pytest
from src.download import cli_context as download_context
from src.orchestration import cli_context as orchestration_context
from tools import CLIToolingContext, CLIToolSettings, OperationOverrideModel

try:
    codeintel_module = importlib.import_module("codeintel.cli_context")
except ImportError:
    codeintel_context = None
else:
    codeintel_context = cast("Any", codeintel_module)


def _assert_settings(module, settings: CLIToolSettings) -> None:
    """Assert that settings match the module's CLI configuration.

    Parameters
    ----------
    module
        Module object containing CLI_INTERFACE_ID and CLI_TITLE attributes.
    settings : CLIToolSettings
        Settings object to validate.
    """
    assert isinstance(settings, CLIToolSettings)
    assert settings.interface_id == module.CLI_INTERFACE_ID
    assert settings.title == module.CLI_TITLE


def _assert_context(context: CLIToolingContext) -> None:
    """Assert that context has required attributes.

    Parameters
    ----------
    context : CLIToolingContext
        Context object to validate.
    """
    assert isinstance(context, CLIToolingContext)
    assert hasattr(context, "augment")
    assert hasattr(context, "registry")


def test_download_cli_context_helpers() -> None:
    """Test download CLI context helper functions."""
    settings = download_context.get_cli_settings()
    _assert_settings(download_context, settings)

    context = download_context.get_cli_context()
    _assert_context(context)

    assert download_context.get_cli_config().operation_context is not None
    assert download_context.get_operation_override("missing") is None


def test_orchestration_cli_context_helpers() -> None:
    """Test orchestration CLI context helper functions."""
    settings = orchestration_context.get_cli_settings()
    _assert_settings(orchestration_context, settings)

    context = orchestration_context.get_cli_context()
    _assert_context(context)

    override = orchestration_context.get_operation_override("index-bm25")
    assert override is None or isinstance(override, OperationOverrideModel)


def test_codeintel_cli_context_helpers() -> None:
    """Test codeintel CLI context helpers (skipped if codeintel package not available)."""
    if codeintel_context is None:
        pytest.skip("codeintel package not available")
    settings = codeintel_context.get_cli_settings()
    _assert_settings(codeintel_context, settings)

    context = codeintel_context.get_cli_context()
    _assert_context(context)

    override = codeintel_context.get_operation_override("symbols")
    assert override is None or isinstance(override, OperationOverrideModel)
