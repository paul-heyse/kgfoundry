"""File-level processing for the docstring builder pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from importlib import import_module
from typing import TYPE_CHECKING, Protocol, cast

from tools.docstring_builder.builder_types import ExitStatus
from tools.docstring_builder.config_models import DocstringApplyConfig
from tools.docstring_builder.docfacts import build_docfacts
from tools.docstring_builder.harvest import harvest_file
from tools.docstring_builder.io import matches_patterns
from tools.docstring_builder.models import DocstringBuilderError
from tools.docstring_builder.observability import record_operation_metrics
from tools.docstring_builder.paths import REPO_ROOT
from tools.docstring_builder.pipeline_types import FileOutcome

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from tools.docstring_builder.builder_types import LoggerLike
    from tools.docstring_builder.cache import DocstringBuilderCache
    from tools.docstring_builder.config import BuilderConfig
    from tools.docstring_builder.docfacts import DocFact
    from tools.docstring_builder.harvest import HarvestResult
    from tools.docstring_builder.ir import IRDocstring
    from tools.docstring_builder.pipeline_types import ProcessingOptions
    from tools.docstring_builder.plugins import PluginManager
    from tools.docstring_builder.schema import DocstringEdit
    from tools.docstring_builder.semantics import SemanticResult

try:  # pragma: no cover - optional dependency at runtime
    from libcst import ParserSyntaxError as _ParserSyntaxError
except ModuleNotFoundError:  # pragma: no cover - defensive guard for optional import
    _PARSER_SYNTAX_ERRORS: tuple[type[BaseException], ...] = ()
else:
    _PARSER_SYNTAX_ERRORS = cast("tuple[type[BaseException], ...]", (_ParserSyntaxError,))

_HARVEST_ERRORS: tuple[type[BaseException], ...] = (
    *_PARSER_SYNTAX_ERRORS,
    DocstringBuilderError,
    OSError,
)


class CollectEditsCallable(Protocol):
    """Protocol for collecting docstring edits from harvested symbols."""

    def __call__(
        self,
        result: HarvestResult,
        config: BuilderConfig,
        plugin_manager: PluginManager | None,
        *,
        format_only: bool = False,
    ) -> tuple[list[DocstringEdit], list[SemanticResult], list[IRDocstring]]:
        """Return semantic artifacts, edits, and IR entries for a harvested module."""
        raise NotImplementedError


class ApplyEditsCallable(Protocol):
    """Protocol for applying rendered docstrings to source files."""

    def __call__(
        self,
        result: HarvestResult,
        edits: Iterable[DocstringEdit],
        *,
        apply_config: DocstringApplyConfig | None = None,
    ) -> tuple[bool, str | None]:
        """Apply rendered docstrings and return change status plus optional preview."""
        raise NotImplementedError


def _load_apply_edits() -> ApplyEditsCallable:
    """Load and return the apply_edits function from the apply module.

    Returns
    -------
    ApplyEditsCallable
        Callable that applies docstring edits to source files.
    """
    module = import_module("tools.docstring_builder.apply")
    return cast("ApplyEditsCallable", module.apply_edits)


@dataclass(slots=True, frozen=True)
class FileProcessingContext:
    """Context for file processing with mutable state."""

    docfacts: list[DocFact]
    preview: str | None
    changed: bool
    skipped: bool
    message: str | None


@dataclass(slots=True, frozen=True)
class FileProcessor:
    """Process individual files for the docstring builder."""

    config: BuilderConfig
    cache: DocstringBuilderCache
    options: ProcessingOptions
    collect_edits: CollectEditsCallable
    plugin_manager: PluginManager | None = None
    logger: LoggerLike = field(default_factory=lambda: logging.getLogger(__name__))

    def process(self, file_path: Path) -> FileOutcome:
        """Harvest, render, and apply docstrings for a single file.

        Parameters
        ----------
        file_path : Path
            Path to the file to process.

        Returns
        -------
        FileOutcome
            Outcome containing status, docfacts, preview, and change information.
        """
        command = self.options.command
        is_update = command in {"update", "fmt"}
        is_check = command == "check"
        ctx = FileProcessingContext(
            docfacts=[],
            preview=None,
            changed=False,
            skipped=False,
            message=None,
        )

        if self._use_cache(file_path):
            ctx.skipped = True
            ctx.message = "cache fresh"
            return FileOutcome(
                status=ExitStatus.SUCCESS,
                docfacts=ctx.docfacts,
                preview=ctx.preview,
                changed=ctx.changed,
                skipped=ctx.skipped,
                message=ctx.message,
                cache_hit=True,
            )

        # Try to harvest and process file
        result_or_outcome = self._try_harvest(file_path)
        if isinstance(result_or_outcome, FileOutcome):
            return result_or_outcome
        result = result_or_outcome

        edits, semantics, ir_entries = self.collect_edits(
            result,
            self.config,
            self.plugin_manager,
            format_only=command == "fmt",
        )

        # Handle harvest-only command
        if command == "harvest":
            ctx.docfacts = build_docfacts(semantics)
            return FileOutcome(
                status=ExitStatus.SUCCESS,
                docfacts=ctx.docfacts,
                preview=ctx.preview,
                changed=ctx.changed,
                skipped=ctx.skipped,
                message=ctx.message,
                semantics=list(semantics),
                ir=list(ir_entries),
            )

        # Handle no-semantics case
        if not semantics:
            if is_update:
                self.cache.update(file_path, self.config.config_hash)
            ctx.message = "no managed symbols"
            return FileOutcome(
                status=ExitStatus.SUCCESS,
                docfacts=ctx.docfacts,
                preview=ctx.preview,
                changed=ctx.changed,
                skipped=ctx.skipped,
                message=ctx.message,
                semantics=list(semantics),
                ir=list(ir_entries),
            )

        # Process edits for update/check/fmt
        ctx.docfacts = build_docfacts(semantics)
        if not edits:
            if is_update:
                self.cache.update(file_path, self.config.config_hash)
            ctx.message = "no edits needed"
            return FileOutcome(
                status=ExitStatus.SUCCESS,
                docfacts=ctx.docfacts,
                preview=ctx.preview,
                changed=ctx.changed,
                skipped=ctx.skipped,
                message=ctx.message,
                semantics=list(semantics),
                ir=list(ir_entries),
            )

        # Apply edits
        should_write = is_update or (is_check and bool(self.options.baseline))
        apply_config = (
            DocstringApplyConfig()
            if should_write
            else DocstringApplyConfig(write_changes=False, atomic_writes=False)
        )
        ctx.changed, ctx.preview = self._apply_edits(
            result,
            edits,
            apply_config=apply_config,
        )
        if is_update:
            self.cache.update(file_path, self.config.config_hash)

        # Determine exit status
        status = ExitStatus.SUCCESS
        if command == "check" and not self.options.baseline and ctx.changed:
            status = ExitStatus.VIOLATION
            ctx.message = "docstring mismatch"

        return FileOutcome(
            status=status,
            docfacts=ctx.docfacts,
            preview=ctx.preview,
            changed=ctx.changed,
            skipped=ctx.skipped,
            message=ctx.message,
            semantics=list(semantics),
            ir=list(ir_entries),
        )

    def _try_harvest(self, file_path: Path) -> HarvestResult | FileOutcome:
        """Attempt to harvest a file, returning outcome on error.

        Parameters
        ----------
        file_path : Path
            Path to the file to harvest.

        Returns
        -------
        HarvestResult | FileOutcome
            HarvestResult on success, FileOutcome on error.

        Raises
        ------
        KeyboardInterrupt
            Propagated if user interrupts the operation.
        """
        result: HarvestResult | FileOutcome | None = None
        try:
            with record_operation_metrics("harvest", status="success"):
                result = harvest_file(file_path, self.config, REPO_ROOT)
            if self.plugin_manager is not None:
                result = self.plugin_manager.apply_harvest(file_path, result)
        except ModuleNotFoundError as exc:
            relative = file_path.relative_to(REPO_ROOT)
            message = f"missing dependency: {exc}"
            if self._can_ignore_missing(file_path):
                self.logger.info("Skipping %s due to missing dependency: %s", relative, exc)
                result = FileOutcome(
                    status=ExitStatus.SUCCESS,
                    docfacts=[],
                    preview=None,
                    changed=False,
                    skipped=True,
                    message=message,
                )
            else:
                self.logger.exception("Failed to harvest %s", relative)
                result = FileOutcome(
                    status=ExitStatus.CONFIG,
                    docfacts=[],
                    preview=None,
                    changed=False,
                    skipped=False,
                    message=message,
                )
        except _HARVEST_ERRORS as exc:
            self.logger.exception("Failed to harvest %s", file_path)
            result = FileOutcome(
                status=ExitStatus.ERROR,
                docfacts=[],
                preview=None,
                changed=False,
                skipped=False,
                message=str(exc),
            )
        except KeyboardInterrupt:  # pragma: no cover - propagate user interrupt
            raise

        if isinstance(result, FileOutcome):
            return result
        return result

    def _use_cache(self, file_path: Path) -> bool:
        """Return ``True`` when cached results remain valid.

        Parameters
        ----------
        file_path : Path
            Path to the file to check.

        Returns
        -------
        bool
            True if cache is valid and should be used, False otherwise.
        """
        command = self.options.command
        return (
            command != "harvest"
            and not self.options.force
            and not self.cache.needs_update(file_path, self.config.config_hash)
        )

    def _can_ignore_missing(self, file_path: Path) -> bool:
        """Return ``True`` if missing dependencies can be ignored.

        Parameters
        ----------
        file_path : Path
            Path to the file to check.

        Returns
        -------
        bool
            True if missing dependencies can be ignored for this file.
        """
        return self.options.ignore_missing and matches_patterns(
            file_path, self.options.missing_patterns
        )

    @staticmethod
    def _apply_edits(
        result: HarvestResult,
        edits: Sequence[DocstringEdit],
        *,
        apply_config: DocstringApplyConfig,
    ) -> tuple[bool, str | None]:
        """Apply docstring edits and return change status plus preview.

        Parameters
        ----------
        result : HarvestResult
            Harvested module metadata.
        edits : Sequence[DocstringEdit]
            Docstring edits to apply.
        apply_config : DocstringApplyConfig
            Configuration for applying edits.

        Returns
        -------
        tuple[bool, str | None]
            Tuple of (changed, preview) where changed indicates if edits were applied,
            and preview contains the rendered code when in dry-run mode.
        """
        changed = False
        preview: str | None = None
        if not edits:
            return changed, preview

        apply_edits = _load_apply_edits()
        changed, preview = apply_edits(
            result,
            list(edits),
            apply_config=apply_config,
        )
        return changed, preview
