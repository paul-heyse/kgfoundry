"""Curated public API for KGFoundry tooling.

Install the optional extra ``kgfoundry[tools]`` to access these helpers when the
project is consumed as a wheel. Runtime failures follow :mod:`kgfoundry_common.errors`
and emit Problem Details envelopes consistent with
``schema/examples/tools/problem_details/tool-execution-error.json``.
"""

from __future__ import annotations

import logging
from importlib import import_module
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, cast

from tools._shared.augment_registry import (
    AugmentMetadataModel,
    AugmentRegistryError,
    AugmentRegistryValidationError,
    OperationOverrideModel,
    RegistryInterfaceModel,
    RegistryMetadataModel,
    RegistryOperationModel,
    ToolingMetadataModel,
    load_augment,
    load_registry,
    load_tooling_metadata,
)
from tools._shared.cli import (
    CLI_ENVELOPE_SCHEMA_ID,
    CLI_ENVELOPE_SCHEMA_VERSION,
    CliEnvelope,
    CliEnvelopeBuilder,
    CliErrorEntry,
    CliErrorStatus,
    CliFileResult,
    CliFileStatus,
    CliStatus,
    new_cli_envelope,
    render_cli_envelope,
    validate_cli_envelope,
)
from tools._shared.cli_integration import cli_operation
from tools._shared.cli_runtime import (
    CliContext,
    CliRunConfig,
    CliRunStatus,
    EnvelopeBuilder,
    cli_run,
    normalize_route,
    normalize_token,
    sha256_file,
)
from tools._shared.cli_tooling import (
    CLIConfigError,
    CLIToolingContext,
    CLIToolSettings,
    load_cli_tooling_context,
)
from tools._shared.logging import (
    StructuredLoggerAdapter,
    get_logger,
    with_fields,
)
from tools._shared.metrics import ToolRunObservation, observe_tool_run
from tools._shared.observability import MetricEmitterError, emitter
from tools._shared.paths import Paths
from tools._shared.problem_details import (
    ExceptionProblemDetailsParams,
    JsonValue,
    ProblemDetailsDict,
    ProblemDetailsParams,
    SchemaProblemDetailsParams,
    ToolProblemDetailsParams,
    build_problem_details,
    build_schema_problem_details,
    build_tool_problem_details,
    problem_from_exception,
    render_problem,
    tool_digest_mismatch_problem_details,
    tool_disallowed_problem_details,
    tool_failure_problem_details,
    tool_missing_problem_details,
    tool_timeout_problem_details,
)
from tools._shared.proc import (
    ProcessRunner,
    ToolExecutionError,
    ToolRunResult,
    get_process_runner,
    run_tool,
    set_process_runner,
)
from tools._shared.schema import validate_tools_payload
from tools._shared.settings import (
    SettingsError,
    ToolRuntimeSettings,
    get_runtime_settings,
)
from tools._shared.validation import (
    ValidationError,
    require_directory,
    require_file,
    resolve_path,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, MutableMapping
    from types import ModuleType

    from tools import (
        codemods,
        docs,
        docstring_builder,
        gen_readmes,
        generate_pr_summary,
        navmap,
    )

logging.getLogger(__name__).addHandler(logging.NullHandler())

_PUBLIC_EXPORTS: dict[str, object] = {
    "AugmentMetadataModel": AugmentMetadataModel,
    "AugmentRegistryError": AugmentRegistryError,
    "AugmentRegistryValidationError": AugmentRegistryValidationError,
    "CLI_ENVELOPE_SCHEMA_ID": CLI_ENVELOPE_SCHEMA_ID,
    "CLI_ENVELOPE_SCHEMA_VERSION": CLI_ENVELOPE_SCHEMA_VERSION,
    "CLIConfigError": CLIConfigError,
    "CLIToolSettings": CLIToolSettings,
    "CLIToolingContext": CLIToolingContext,
    "CliEnvelope": CliEnvelope,
    "CliEnvelopeBuilder": CliEnvelopeBuilder,
    "CliErrorEntry": CliErrorEntry,
    "CliErrorStatus": CliErrorStatus,
    "CliFileResult": CliFileResult,
    "CliFileStatus": CliFileStatus,
    "CliStatus": CliStatus,
    "ExceptionProblemDetailsParams": ExceptionProblemDetailsParams,
    "JsonValue": JsonValue,
    "OperationOverrideModel": OperationOverrideModel,
    "ProblemDetailsDict": ProblemDetailsDict,
    "ProblemDetailsParams": ProblemDetailsParams,
    "SchemaProblemDetailsParams": SchemaProblemDetailsParams,
    "SettingsError": SettingsError,
    "StructuredLoggerAdapter": cast("object", StructuredLoggerAdapter),
    "CliContext": CliContext,
    "CliRunConfig": CliRunConfig,
    "cli_operation": cli_operation,
    "CliRunStatus": CliRunStatus,
    "EnvelopeBuilder": EnvelopeBuilder,
    "ProcessRunner": ProcessRunner,
    "ToolExecutionError": ToolExecutionError,
    "ToolRunObservation": ToolRunObservation,
    "ToolRunResult": ToolRunResult,
    "ToolingMetadataModel": ToolingMetadataModel,
    "ToolRuntimeSettings": cast("object", ToolRuntimeSettings),
    "ToolProblemDetailsParams": ToolProblemDetailsParams,
    "ValidationError": ValidationError,
    "build_problem_details": build_problem_details,
    "build_schema_problem_details": build_schema_problem_details,
    "build_tool_problem_details": build_tool_problem_details,
    "get_process_runner": get_process_runner,
    "get_logger": get_logger,
    "get_runtime_settings": get_runtime_settings,
    "logging": logging,
    "new_cli_envelope": new_cli_envelope,
    "load_augment": load_augment,
    "load_cli_tooling_context": load_cli_tooling_context,
    "load_registry": load_registry,
    "load_tooling_metadata": load_tooling_metadata,
    "cli_run": cli_run,
    "normalize_route": normalize_route,
    "normalize_token": normalize_token,
    "sha256_file": sha256_file,
    "observe_tool_run": observe_tool_run,
    "Paths": Paths,
    "MetricEmitterError": MetricEmitterError,
    "emitter": emitter,
    "problem_from_exception": problem_from_exception,
    "render_cli_envelope": render_cli_envelope,
    "render_problem": render_problem,
    "RegistryInterfaceModel": RegistryInterfaceModel,
    "RegistryMetadataModel": RegistryMetadataModel,
    "RegistryOperationModel": RegistryOperationModel,
    "require_directory": require_directory,
    "require_file": require_file,
    "resolve_path": resolve_path,
    "run_tool": run_tool,
    "tool_digest_mismatch_problem_details": tool_digest_mismatch_problem_details,
    "set_process_runner": set_process_runner,
    "tool_disallowed_problem_details": tool_disallowed_problem_details,
    "tool_failure_problem_details": tool_failure_problem_details,
    "tool_missing_problem_details": tool_missing_problem_details,
    "tool_timeout_problem_details": tool_timeout_problem_details,
    "validate_cli_envelope": validate_cli_envelope,
    "validate_tools_payload": validate_tools_payload,
    "with_fields": with_fields,
}

PUBLIC_EXPORTS: Final[Mapping[str, object]] = MappingProxyType(_PUBLIC_EXPORTS)

_MODULE_EXPORTS: dict[str, str] = {
    "cli_context_registry": "tools.cli_context_registry",
    "codemods": "tools.codemods",
    "docs": "tools.docs",
    "docstring_builder": "tools.docstring_builder",
    "gen_readmes": "tools.gen_readmes",
    "generate_pr_summary": "tools.generate_pr_summary",
    "navmap": "tools.navmap",
}

MODULE_EXPORTS: Final[Mapping[str, str]] = MappingProxyType(_MODULE_EXPORTS)

__all__: tuple[str, ...] = (
    "CLI_ENVELOPE_SCHEMA_ID",
    "CLI_ENVELOPE_SCHEMA_VERSION",
    "AugmentMetadataModel",
    "AugmentRegistryError",
    "AugmentRegistryValidationError",
    "CLIConfigError",
    "CLIToolSettings",
    "CLIToolingContext",
    "CliContext",
    "CliEnvelope",
    "CliEnvelopeBuilder",
    "CliErrorEntry",
    "CliErrorStatus",
    "CliFileResult",
    "CliFileStatus",
    "CliRunConfig",
    "CliRunStatus",
    "CliStatus",
    "EnvelopeBuilder",
    "ExceptionProblemDetailsParams",
    "JsonValue",
    "MetricEmitterError",
    "OperationOverrideModel",
    "Paths",
    "ProblemDetailsDict",
    "ProblemDetailsParams",
    "ProcessRunner",
    "RegistryInterfaceModel",
    "RegistryMetadataModel",
    "RegistryOperationModel",
    "SchemaProblemDetailsParams",
    "SettingsError",
    "StructuredLoggerAdapter",
    "ToolExecutionError",
    "ToolProblemDetailsParams",
    "ToolRunObservation",
    "ToolRunResult",
    "ToolRuntimeSettings",
    "ToolingMetadataModel",
    "ValidationError",
    "build_problem_details",
    "build_schema_problem_details",
    "build_tool_problem_details",
    "cli_operation",
    "cli_run",
    "codemods",
    "docs",
    "docstring_builder",
    "emitter",
    "gen_readmes",
    "generate_pr_summary",
    "get_logger",
    "get_process_runner",
    "get_runtime_settings",
    "logging",
    "navmap",
    "new_cli_envelope",
    "normalize_route",
    "normalize_token",
    "observe_tool_run",
    "problem_from_exception",
    "render_cli_envelope",
    "render_problem",
    "require_directory",
    "require_file",
    "resolve_path",
    "run_tool",
    "set_process_runner",
    "sha256_file",
    "tool_digest_mismatch_problem_details",
    "tool_disallowed_problem_details",
    "tool_failure_problem_details",
    "tool_missing_problem_details",
    "tool_timeout_problem_details",
    "validate_cli_envelope",
    "validate_tools_payload",
    "with_fields",
)


def __getattr__(name: str) -> ModuleType:
    """Get module attribute via lazy import.

    Parameters
    ----------
    name : str
        Module name to import.

    Returns
    -------
    ModuleType
        Imported module.

    Raises
    ------
    AttributeError
        If the module name is not in MODULE_EXPORTS.
    """
    if name in MODULE_EXPORTS:
        module = import_module(MODULE_EXPORTS[name])
        namespace = cast("MutableMapping[str, object]", globals())
        namespace[name] = module
        _PUBLIC_EXPORTS[name] = cast("object", module)
        return module
    message = f"module 'tools' has no attribute {name!r}"
    raise AttributeError(message)


def __dir__() -> list[str]:
    """Return list of available module attributes.

    Returns
    -------
    list[str]
        Sorted list of attribute names including lazy imports.
    """
    namespace = cast("MutableMapping[str, object]", globals())
    return sorted({*namespace, *MODULE_EXPORTS.keys()})
