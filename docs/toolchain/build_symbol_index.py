"""Build documentation symbol index artifacts with shared lifecycle helpers."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from tools import JsonValue, ToolExecutionError

from docs._scripts import build_symbol_index as legacy_index
from docs.toolchain._shared.lifecycle import (
    DocLifecycle,
    DocToolError,
    DocToolMetadata,
    DocToolSettings,
    ProblemDetailsInput,
    create_doc_tool_context,
)
from kgfoundry_common.errors import (
    DeserializationError,
    SchemaValidationError,
    SerializationError,
)

if TYPE_CHECKING:
    from docs.toolchain._shared import DocToolContext
else:  # pragma: no cover - runtime alias for type checking
    DocToolContext = object


@dataclass(slots=True, frozen=True)
class _ArtifactSummary:
    """Outcome flags for symbol index artifacts."""

    symbols_written: bool
    by_file_written: bool
    by_module_written: bool
    symbol_count: int


@dataclass(slots=True, frozen=True)
class _ArtifactPaths:
    """Filesystem targets for symbol index artifacts."""

    symbols: Path
    by_file: Path
    by_module: Path
    schema: Path


def build_symbol_index(argv: Sequence[str] | None = None) -> int:
    """Entry point for the symbol index build operation.

    Parameters
    ----------
    argv : Sequence[str] | None, optional
        Optional command-line arguments overriding ``sys.argv``.

    Returns
    -------
    int
        Exit code signalling success (0) or failure (non-zero).
    """
    settings = DocToolSettings.parse_args(
        argv,
        metadata=DocToolMetadata(
            operation="build_symbol_index",
            description="Build schema-validated documentation symbol index artifacts.",
            problem_type="docs-symbol-index",
        ),
    )
    context = create_doc_tool_context(settings)
    lifecycle = DocLifecycle(context)
    return lifecycle.run(_run_symbol_index)


def _run_symbol_index(context: DocToolContext) -> int:
    settings = context.settings
    docs_build_dir = settings.docs_build_dir
    paths = _ArtifactPaths(
        symbols=docs_build_dir / "symbols.json",
        by_file=docs_build_dir / "by_file.json",
        by_module=docs_build_dir / "by_module.json",
        schema=settings.root / "schema" / "docs" / "symbol-index.schema.json",
    )

    packages = list(settings.docs_settings.packages)

    try:
        artifacts = legacy_index.generate_index(packages, legacy_index.LOADER)
        summary = _write_artifacts(
            context,
            artifacts,
            paths=paths,
        )
    except DocToolError:
        raise
    except ToolExecutionError as exc:  # pragma: no cover - exercised via CLI smoke
        problem = exc.problem or context.problem_details(
            ProblemDetailsInput(
                title="Symbol index build failed",
                detail=str(exc),
                status=500,
                instance=context.instance("tool-error"),
                extensions={"command": cast("JsonValue", list(exc.command))},
            )
        )
        message = "Symbol index build failed"
        raise DocToolError(
            message,
            problem=problem,
            exit_code=exc.returncode or 1,
            status_label="error",
        ) from exc
    except (
        DeserializationError,
        SerializationError,
        SchemaValidationError,
        OSError,
        RuntimeError,
        json.JSONDecodeError,
    ) as exc:
        problem = context.problem_details(
            ProblemDetailsInput(
                title="Symbol index build failed",
                detail=str(exc),
                status=500,
                instance=context.instance("unexpected-error"),
                extensions={"packages": cast("JsonValue", [str(pkg) for pkg in packages])},
            )
        )
        message = "Symbol index build failed"
        raise DocToolError(
            message,
            problem=problem,
            exit_code=1,
            status_label="error",
        ) from exc

    context.logger.info(
        "Symbol index build complete",
        extra={
            "status": "success",
            "symbols_entries": summary.symbol_count,
            "symbols_updated": summary.symbols_written,
            "by_file_updated": summary.by_file_written,
            "by_module_updated": summary.by_module_written,
            "symbols_path": str(paths.symbols),
            "by_file_path": str(paths.by_file),
            "by_module_path": str(paths.by_module),
        },
    )
    return 0


def _write_artifacts(
    context: DocToolContext,
    artifacts: legacy_index.SymbolIndexArtifacts,
    *,
    paths: _ArtifactPaths,
) -> _ArtifactSummary:
    symbols_written = legacy_index.write_artifact(
        paths.symbols,
        artifacts.rows_payload(),
        logger=context.bind(artifact="symbols.json"),
        artifact="symbols.json",
        validation=legacy_index.SchemaValidation(schema=paths.schema),
    )
    by_file_written = legacy_index.write_artifact(
        paths.by_file,
        artifacts.by_file_payload(),
        logger=context.bind(artifact="by_file.json"),
        artifact="by_file.json",
    )
    by_module_written = legacy_index.write_artifact(
        paths.by_module,
        artifacts.by_module_payload(),
        logger=context.bind(artifact="by_module.json"),
        artifact="by_module.json",
    )
    return _ArtifactSummary(
        symbols_written=symbols_written,
        by_file_written=by_file_written,
        by_module_written=by_module_written,
        symbol_count=artifacts.symbol_count,
    )


__all__ = ["build_symbol_index"]
