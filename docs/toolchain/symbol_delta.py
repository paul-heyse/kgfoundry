"""Generate documentation symbol delta artifacts with lifecycle instrumentation."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from tools import ToolExecutionError

from docs._scripts import symbol_delta as legacy_delta
from docs.toolchain._shared.lifecycle import (
    DocLifecycle,
    DocToolContext,
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


def symbol_delta(argv: Sequence[str] | None = None) -> int:
    """Entry point for symbol delta generation.

    Parameters
    ----------
    argv : Sequence[str] | None, optional
        Optional command-line arguments overriding ``sys.argv``.

    Returns
    -------
    int
        Exit code indicating success (0) or failure.
    """
    settings = DocToolSettings.parse_args(
        argv,
        metadata=DocToolMetadata(
            operation="symbol_delta",
            description="Compute documentation symbol delta artifacts.",
            problem_type="docs-symbol-delta",
        ),
        configure=_configure_parser,
    )
    context = create_doc_tool_context(settings)
    lifecycle = DocLifecycle(context)
    return lifecycle.run(_run_symbol_delta)


@dataclass(slots=True, frozen=True)
class _DeltaOptions:
    """CLI options materialised for delta generation."""

    base: str
    output: Path

    @classmethod
    def from_context(cls, context: DocToolContext) -> _DeltaOptions:
        base_raw = context.settings.get_arg("base", "HEAD~1")
        base = str(base_raw)
        output_raw = context.settings.get_arg("output")
        if output_raw is None:
            output_path = context.settings.docs_build_dir / "symbols.delta.json"
        else:
            candidate = Path(str(output_raw))
            if not candidate.is_absolute():
                candidate = (context.settings.docs_build_dir / candidate).resolve()
            output_path = candidate
        return cls(base=base, output=output_path)


def _configure_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--base",
        default="HEAD~1",
        help="Git ref or symbols.json path providing the baseline snapshot.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Destination path for the generated delta (defaults to docs/_build).",
    )


def _run_symbol_delta(context: DocToolContext) -> int:
    options = _DeltaOptions.from_context(context)
    symbols_path = context.settings.docs_build_dir / "symbols.json"

    if not symbols_path.exists():
        detail = f"Missing current snapshot: {symbols_path}"
        problem = context.problem_details(
            ProblemDetailsInput(
                title="Symbol delta computation failed",
                detail=detail,
                status=404,
                instance=context.instance("missing-current"),
            )
        )
        message = "Current symbol snapshot missing"
        raise DocToolError(
            message,
            problem=problem,
            exit_code=1,
            status_label="error",
        )

    try:
        head_rows = legacy_delta.load_symbol_rows(symbols_path)
        base_rows, base_sha = legacy_delta.load_base_snapshot(options.base)
        head_sha = legacy_delta.git_rev_parse("HEAD")
        payload = legacy_delta.build_delta_payload(
            base_rows=base_rows,
            head_rows=head_rows,
            base_sha=base_sha,
            head_sha=head_sha,
        )
        delta_written = legacy_delta.write_delta(options.output, payload)
    except DocToolError:
        raise
    except ToolExecutionError as exc:  # pragma: no cover - exercised via CLI smoke
        problem = exc.problem or context.problem_details(
            ProblemDetailsInput(
                title="Symbol delta computation failed",
                detail=str(exc),
                status=500,
                instance=context.instance("tool-error"),
                extensions={"command": list(exc.command)},
            )
        )
        message = "Symbol delta computation failed"
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
                title="Symbol delta computation failed",
                detail=str(exc),
                status=500,
                instance=context.instance("unexpected-error"),
                extensions={"base": options.base},
            )
        )
        message = "Symbol delta computation failed"
        raise DocToolError(
            message,
            problem=problem,
            exit_code=1,
            status_label="error",
        ) from exc

    context.logger.info(
        "Symbol delta computation complete",
        extra={
            "status": "success",
            "delta_path": str(options.output),
            "delta_written": delta_written,
            "base_ref": options.base,
            "base_sha": base_sha,
            "head_sha": head_sha,
        },
    )
    return 0


__all__ = ["symbol_delta"]
