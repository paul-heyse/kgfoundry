"""Shared CLI context for the orchestration command suite.

This module mirrors the shared tooling helpers introduced for other CLIs
(for example, ``download``) so orchestration commands can load typed augment
and registry metadata without duplicating configuration logic. The
helpers expose cached accessors for the `CLIToolSettings`, `CLIToolingContext`,
and associated metadata models consumed by downstream tooling (OpenAPI
generation, MkDocs diagrams, navmap loader, etc.).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, cast

from tools import (
    AugmentMetadataModel,
    CLIToolingContext,
    CLIToolSettings,
    OperationOverrideModel,
    RegistryInterfaceModel,
    RegistryMetadataModel,
    ToolingMetadataModel,
)
from tools.cli_context_registry import (
    CLIContextDefinition,
    augment_for,
    context_for,
    default_version_resolver,
    interface_for,
    operation_override_for,
    register_cli,
    registry_for,
    settings_for,
    tooling_metadata_for,
)

if TYPE_CHECKING:
    from tools.typer_to_openapi_cli import CLIConfig, OperationContext


REPO_ROOT = Path(__file__).resolve().parents[2]
"""Repository root, used to locate augment and registry metadata."""


CLI_OPERATION_IDS: dict[str, str] = {
    "index-bm25": "cli.index_bm25",
    "index_bm25": "cli.index_bm25",
    "index-faiss": "cli.index_faiss",
    "index_faiss": "cli.index_faiss",
    "api": "cli.api",
    "e2e": "cli.e2e",
}
"""Mapping of subcommand names to canonical operation identifiers."""


_CLI_KEY = "orchestration"
_CLI_DEFINITION = CLIContextDefinition(
    command="orchestration",
    title="KGFoundry Orchestration",
    interface_id="orchestration-cli",
    operation_ids=CLI_OPERATION_IDS,
    bin_name="kgf",
    version_resolver=default_version_resolver("kgfoundry"),
)

register_cli(_CLI_KEY, _CLI_DEFINITION)

CLI_COMMAND = _CLI_DEFINITION.command
"""Root command label used for CLI envelopes and logging."""


CLI_TITLE = _CLI_DEFINITION.title
"""Human-readable CLI title consumed by Typer help text and OpenAPI metadata."""


CLI_INTERFACE_ID = _CLI_DEFINITION.interface_id
"""Registry interface identifier for the orchestration CLI suite."""


def get_cli_settings() -> CLIToolSettings:
    """Return CLI settings describing augment and registry metadata inputs.

    Returns
    -------
    CLIToolSettings
        Cached settings referencing augment and registry metadata paths.
    """
    return settings_for(_CLI_KEY)


def get_cli_context() -> CLIToolingContext:
    """Return the cached CLI tooling context for orchestration commands.

    Returns
    -------
    CLIToolingContext
        Composite context bundling augment, registry, and CLI config.
    """
    return context_for(_CLI_KEY)


def get_cli_config() -> CLIConfig:
    """Return the typed CLI configuration extracted from the tooling context.

    Returns
    -------
    CLIConfig
        Typed configuration consumed by CLI generators.
    """
    context = get_cli_context()
    return cast("CLIConfig", context.cli_config)


def get_operation_context() -> OperationContext:
    """Return the operation context helper used for OpenAPI generation.

    Returns
    -------
    OperationContext
        Helper used by tooling to resolve operation metadata.
    """
    return get_cli_config().operation_context


def get_tooling_metadata() -> ToolingMetadataModel:
    """Return the composite augment/registry metadata bundle for orchestration.

    Returns
    -------
    ToolingMetadataModel
        Immutable bundle combining augment and registry metadata.
    """
    return tooling_metadata_for(_CLI_KEY)


def get_augment_metadata() -> AugmentMetadataModel:
    """Return augment metadata for orchestration operations.

    Returns
    -------
    AugmentMetadataModel
        Augment metadata describing orchestration CLI operations.
    """
    return augment_for(_CLI_KEY)


def get_registry_metadata() -> RegistryMetadataModel:
    """Return registry metadata backing the orchestration CLI interface.

    Returns
    -------
    RegistryMetadataModel
        Registry metadata describing orchestration interfaces.
    """
    return registry_for(_CLI_KEY)


def get_interface_metadata() -> RegistryInterfaceModel:
    """Return registry interface metadata for the orchestration CLI.

    Returns
    -------
    RegistryInterfaceModel
        Interface metadata linked to the orchestration CLI.
    """
    return interface_for(_CLI_KEY)


def get_operation_override(
    subcommand: str, *, tokens: Sequence[str] | None = None
) -> OperationOverrideModel | None:
    """Return augment override metadata for the given subcommand when available.

    Parameters
    ----------
    subcommand : str
        CLI subcommand name to look up.
    tokens : Sequence[str] | None, optional
        Optional command tokens for nested operation resolution.

    Returns
    -------
    OperationOverrideModel | None
        Augment override metadata when defined; otherwise ``None``.
    """
    return operation_override_for(_CLI_KEY, subcommand=subcommand, tokens=tokens)


__all__ = [
    "CLI_COMMAND",
    "CLI_INTERFACE_ID",
    "CLI_OPERATION_IDS",
    "CLI_TITLE",
    "REPO_ROOT",
    "get_augment_metadata",
    "get_cli_config",
    "get_cli_context",
    "get_cli_settings",
    "get_interface_metadata",
    "get_operation_context",
    "get_operation_override",
    "get_registry_metadata",
    "get_tooling_metadata",
]
