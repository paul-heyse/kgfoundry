"""Pipeline execution context builder with full dependency resolution.

This module encapsulates context setup for docstring builder pipeline execution,
including logger initialization, plugin loading, policy engine setup, and
option assembly. It handles all configuration errors and returns either a
fully-built context or a typed error result.

Ownership: docstring-builder team
Version: 1.0
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from tools._shared.logging import get_logger, with_fields
from tools.docstring_builder.builder_types import (
    DocstringBuildResult,
    ExitStatus,
)
from tools.docstring_builder.observability import get_correlation_id
from tools.docstring_builder.orchestrator import _build_error_result
from tools.docstring_builder.paths import REPO_ROOT
from tools.docstring_builder.pipeline_types import ProcessingOptions
from tools.docstring_builder.plugins import (
    PluginConfigurationError,
    load_plugins,
)
from tools.docstring_builder.policy import (
    PolicyConfigurationError,
    PolicyEngine,
    load_policy_settings,
)
from tools.docstring_builder.utils import optional_str

if TYPE_CHECKING:
    from pathlib import Path

    from tools.docstring_builder.builder_types import (
        DocstringBuildRequest,
        LoggerLike,
    )
    from tools.docstring_builder.config import BuilderConfig, ConfigSelection
    from tools.docstring_builder.plugins import (
        PluginManager,
    )

MISSING_MODULE_PATTERNS = ("docs/_build/**",)
LOGGER = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class PipelineContextBuilder:
    """Builder for pipeline execution context with full dependency resolution.

    Encapsulates all setup logic for pipeline execution, including:
    - Correlation-aware logger initialization
    - Plugin loading and validation
    - Policy engine setup
    - Processing options assembly

    Handles all configuration errors and returns either a fully-built context
    tuple or a typed DocstringBuildResult for early error exit.

    Parameters
    ----------
    request : DocstringBuildRequest
        The builder request specifying command, options, and mode.
    config : BuilderConfig
        The loaded builder configuration.
    selection : ConfigSelection | None
        The resolved config selection (if any).
    files_list : list[Path]
        The list of files to be processed (for error context).

    Attributes
    ----------
    request : DocstringBuildRequest
        Typed request.
    config : BuilderConfig
        Typed config.
    selection : ConfigSelection | None
        Resolved config selection.
    files_list : list[Path]
        Files for processing.
    """

    request: DocstringBuildRequest
    config: BuilderConfig
    selection: ConfigSelection | None
    files_list: list[Path]

    def build(
        self,
    ) -> (
        tuple[
            LoggerLike,
            PluginManager | None,
            PolicyEngine,
            ProcessingOptions,
        ]
        | DocstringBuildResult
    ):
        """Build execution context or return early error result.

        Attempts to initialize all required components for pipeline execution.
        On any configuration error, returns a typed DocstringBuildResult
        indicating failure, allowing the caller to short-circuit.

        Returns
        -------
        tuple[LoggerLike, PluginManager | None, PolicyEngine, ProcessingOptions] | DocstringBuildResult
            Either a 4-tuple of (logger, plugin_manager, policy_engine, options)
            on success, or a DocstringBuildResult error on configuration failure.

        Notes
        -----
        Errors are logged at exception level with operation context.
        The caller MUST check `isinstance(result, DocstringBuildResult)` to
        detect early exits.
        """
        # Build correlation-aware logger
        logger = self._build_logger()

        # Load and validate plugins
        plugin_manager_or_error = self._load_plugins()
        if isinstance(plugin_manager_or_error, DocstringBuildResult):
            return plugin_manager_or_error
        plugin_manager = plugin_manager_or_error

        # Load and validate policy engine
        policy_engine_or_error = self._load_policy_engine()
        if isinstance(policy_engine_or_error, DocstringBuildResult):
            return policy_engine_or_error
        policy_engine = policy_engine_or_error

        # Build processing options
        options = self._build_processing_options()

        return logger, plugin_manager, policy_engine, options

    def _build_logger(
        self,
    ) -> LoggerLike:
        """Build correlation-aware logger for the pipeline run.

        Returns
        -------
        LoggerLike
            Logger with correlation ID, command, and subcommand fields.
        """
        correlation_id = get_correlation_id()
        command = self.request.command or "unknown"
        subcommand = self.request.invoked_subcommand or self.request.subcommand or command
        return with_fields(
            LOGGER,
            correlation_id=correlation_id,
            command=command,
            subcommand=subcommand,
        )

    def _load_plugins(
        self,
    ) -> PluginManager | DocstringBuildResult | None:
        """Load and validate plugins.

        Returns
        -------
        PluginManager | DocstringBuildResult | None
            The plugin manager on success, None if not available,
            or an error result on configuration failure.
        """
        try:
            return load_plugins(
                self.config,
                REPO_ROOT,
                only=list(self.request.only_plugins),
                disable=list(self.request.disable_plugins),
            )
        except PluginConfigurationError:
            LOGGER.exception("Plugin configuration error", extra={"operation": "plugin_load"})
            return _build_error_result(
                ExitStatus.CONFIG,
                self.request,
                "Plugin configuration error",
                selection=self.selection,
            )

    def _load_policy_engine(
        self,
    ) -> PolicyEngine | DocstringBuildResult:
        """Load and validate policy engine.

        Returns
        -------
        PolicyEngine | DocstringBuildResult
            The policy engine on success, or an error result on failure.
        """
        try:
            policy_settings = load_policy_settings(
                REPO_ROOT, cli_overrides=self.request.policy_overrides
            )
            return PolicyEngine(policy_settings)
        except PolicyConfigurationError:
            LOGGER.exception("Policy configuration error", extra={"operation": "policy_load"})
            return _build_error_result(
                ExitStatus.CONFIG,
                self.request,
                "Policy configuration error",
                selection=self.selection,
            )

    def _build_processing_options(self) -> ProcessingOptions:
        """Build processing options from request and config.

        Returns
        -------
        ProcessingOptions
            Assembled processing options for file processing.
        """
        return ProcessingOptions(
            command=self.request.command or "",
            force=self.request.force,
            ignore_missing=self.request.ignore_missing,
            missing_patterns=tuple(MISSING_MODULE_PATTERNS),
            skip_docfacts=self.request.skip_docfacts,
            baseline=optional_str(self.request.baseline),
        )
