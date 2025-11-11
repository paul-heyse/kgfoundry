from __future__ import annotations

import importlib
from typing import Any, cast

import pytest
from docs import cli_context as docs_cli_context
from src.download import cli_context as download_context
from src.orchestration import cli_context as orchestration_context
from tools import CLIToolingContext, CLIToolSettings, OperationOverrideModel
from tools.docstring_builder import cli_context as docstrings_context
from tools.navmap import cli_context as navmap_context

try:
    codeintel_module = importlib.import_module("codeintel.cli_context")
except ImportError:
    codeintel_context = None
else:
    codeintel_context = cast("Any", codeintel_module)


def _assert_settings(module, settings: CLIToolSettings) -> None:
    assert isinstance(settings, CLIToolSettings)
    assert settings.interface_id == module.CLI_INTERFACE_ID
    assert settings.title == module.CLI_TITLE


def _assert_context(context: CLIToolingContext) -> None:
    assert isinstance(context, CLIToolingContext)
    assert hasattr(context, "augment")
    assert hasattr(context, "registry")


def test_download_cli_context_helpers() -> None:
    settings = download_context.get_cli_settings()
    _assert_settings(download_context, settings)

    context = download_context.get_cli_context()
    _assert_context(context)

    assert download_context.get_cli_config().operation_context is not None
    assert download_context.get_operation_override("missing") is None


def test_orchestration_cli_context_helpers() -> None:
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


def test_navmap_cli_context_helpers() -> None:
    settings = navmap_context.get_cli_settings()
    _assert_settings(navmap_context, settings)

    context = navmap_context.get_cli_context()
    _assert_context(context)

    assert navmap_context.get_operation_override("unknown") is None


def test_docstrings_cli_context_helpers() -> None:
    settings = docstrings_context.get_cli_settings()
    _assert_settings(docstrings_context, settings)

    context = docstrings_context.get_cli_context()
    _assert_context(context)

    override = docstrings_context.get_operation_override("generate")
    assert override is None or isinstance(override, OperationOverrideModel)


def test_docs_scripts_cli_multi_command_support() -> None:
    default_settings = docs_cli_context.get_cli_settings()
    _assert_settings(docs_cli_context, default_settings)

    symbol_settings = docs_cli_context.get_cli_settings("docs-build-symbol-index")
    assert symbol_settings.bin_name == "docs-build-symbol-index"
    assert symbol_settings.interface_id == "docs-symbol-index-cli"

    with pytest.raises(KeyError):
        docs_cli_context.get_cli_settings("unknown-docs-cli")
