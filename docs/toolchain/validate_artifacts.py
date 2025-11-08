"""Validate documentation artifacts with shared lifecycle instrumentation."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from tools import JsonValue

from docs._scripts import validate_artifacts as legacy_validation
from docs.toolchain._shared.lifecycle import (
    DocLifecycle,
    DocToolError,
    DocToolMetadata,
    DocToolSettings,
    ProblemDetailsInput,
    create_doc_tool_context,
)

if TYPE_CHECKING:
    from docs.toolchain._shared import DocToolContext

Validator = Callable[[Path], object]


def validate_artifacts(argv: Sequence[str] | None = None) -> int:
    """Entry point to validate documentation artifacts.

    Parameters
    ----------
    argv : Sequence[str] | None, optional
        Command-line arguments, defaults to sys.argv.

    Returns
    -------
    int
        Exit code: 0 on success, 1 on error.
    """
    settings = DocToolSettings.parse_args(
        argv,
        metadata=DocToolMetadata(
            operation="validate_artifacts",
            description="Validate documentation artifacts against canonical schemas.",
            problem_type="docs-artifact-validation",
        ),
        configure=_configure_parser,
    )
    context = create_doc_tool_context(settings)
    lifecycle = DocLifecycle(context)
    return lifecycle.run(_run_validation)


@dataclass(slots=True, frozen=True)
class _ValidationOptions:
    """CLI options for artifact validation."""

    artifacts: tuple[str, ...] | None

    @classmethod
    def from_context(cls, context: DocToolContext) -> _ValidationOptions:
        raw = context.settings.get_arg("artifacts")
        if raw is None:
            return cls(artifacts=None)
        if isinstance(raw, list):
            return cls(artifacts=tuple(str(item) for item in raw))
        return cls(artifacts=(str(raw),))


def _configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--artifacts",
        nargs="+",
        default=None,
        help="Names of artifacts to validate (defaults to all managed artifacts).",
    )


def _run_validation(context: DocToolContext) -> int:
    options = _ValidationOptions.from_context(context)

    validators: dict[str, Validator] = {
        "symbols.json": legacy_validation.validate_symbol_index,
        "symbols.delta.json": legacy_validation.validate_symbol_delta,
        "by_file.json": legacy_validation.validate_by_file_lookup,
        "by_module.json": legacy_validation.validate_by_module_lookup,
    }

    requested = options.artifacts or tuple(validators.keys())
    validated = 0
    failures: list[dict[str, object]] = []

    for artifact_name in requested:
        artifact_logger = context.bind(artifact=artifact_name)
        validator = validators.get(artifact_name)
        if validator is None:
            artifact_logger.warning(
                "Unknown artifact requested",
                extra={"status": "skipped"},
            )
            continue

        artifact_path = context.settings.docs_build_dir / artifact_name
        try:
            validator(artifact_path)
        except legacy_validation.ArtifactValidationError as exc:
            artifact_logger.exception(
                "Artifact validation failed",
                extra={
                    "status": "failure",
                    "artifact": artifact_name,
                    "error_type": type(exc).__name__,
                },
            )
            failures.append(
                {
                    "artifact": artifact_name,
                    "message": str(exc),
                    "problem": exc.problem,
                    "path": str(artifact_path),
                }
            )
        else:
            validated += 1
            artifact_logger.info(
                "Artifact validated successfully",
                extra={"status": "success"},
            )

    if failures:
        serialized_failures: list[JsonValue] = []
        for failure in failures:
            failure_payload: dict[str, JsonValue] = {
                "artifact": str(failure["artifact"]),
                "message": str(failure["message"]),
                "problem": cast("JsonValue", failure["problem"]),
                "path": str(failure["path"]),
            }
            serialized_failures.append(failure_payload)
        problem = context.problem_details(
            ProblemDetailsInput(
                title="Artifact validation failed",
                detail=f"{len(failures)} artifact(s) failed validation",
                status=500,
                instance=context.instance("validation-failed"),
                extensions={"failedArtifacts": cast("JsonValue", serialized_failures)},
            )
        )
        message = "Artifact validation failed"
        raise DocToolError(message, problem=problem, exit_code=1, status_label="error")

    context.logger.info(
        "All requested artifacts validated successfully",
        extra={
            "status": "success",
            "artifact_count": validated,
        },
    )
    return 0


__all__ = ["validate_artifacts"]
