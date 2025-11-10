"""Fail-fast probe for XTR artifacts.

Example failure payload::

    {
        "type": "https://kgfoundry.dev/problems/resource-unavailable",
        "title": "XTR artifacts unavailable",
        "status": 503,
        "detail": "Index metadata missing.",
        "runtime": "xtr",
        "instance": "/ops/runtime/xtr-open",
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from codeintel_rev.app.config_context import resolve_application_paths
from codeintel_rev.config.settings import load_settings
from codeintel_rev.errors import RuntimeUnavailableError
from codeintel_rev.io.xtr_manager import XTRIndex
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)
APP = typer.Typer(add_completion=False, no_args_is_help=True)
PROBLEM_INSTANCE = "/ops/runtime/xtr-open"
_VERBOSE_DEFAULT = False
_VERBOSE_FLAGS = ("--verbose", "-v")


@APP.command("xtr-open")
def xtr_open(
    root: Annotated[
        Path | None,
        typer.Option(
            "--root",
            help="Override the configured XTR artifact directory.",
            dir_okay=True,
            file_okay=False,
            writable=False,
            readable=True,
        ),
    ] = None,
    *,
    verbose: Annotated[
        bool,
        typer.Option(
            _VERBOSE_DEFAULT,
            *_VERBOSE_FLAGS,
            help="Pretty-print success payloads.",
        ),
    ] = _VERBOSE_DEFAULT,
) -> None:
    """Validate that XTR artifacts are present and readable."""
    settings = load_settings()
    paths = resolve_application_paths(settings)
    xtr_root = root or paths.xtr_dir

    if not settings.xtr.enable:
        _exit_with_problem(
            "XTR disabled via configuration.",
            detail="Set XTR_ENABLE=1 to enable late interaction.",
        )

    if not xtr_root.exists():
        _exit_with_problem(
            "XTR artifacts unavailable",
            detail=f"Directory does not exist: {xtr_root}",
        )

    index = XTRIndex(xtr_root, settings.xtr)
    try:
        index.open()
    except (OSError, RuntimeError, ValueError) as exc:
        LOGGER.exception("xtr_open_failed", extra={"root": str(xtr_root)})
        _exit_with_problem(
            "Failed to open XTR artifacts",
            detail=str(exc),
            cause=exc,
        )

    if not index.ready:
        _exit_with_problem("XTR artifacts loaded but not ready")

    metadata = index.metadata() or {}
    payload = {
        "status": "ready",
        "root": str(xtr_root),
        "chunks": metadata.get("doc_count"),
        "tokens": metadata.get("total_tokens"),
        "dim": metadata.get("dim"),
        "dtype": metadata.get("dtype"),
    }
    typer.echo(json.dumps(payload, indent=2 if verbose else None))


def _exit_with_problem(
    message: str,
    *,
    detail: str | None = None,
    cause: Exception | None = None,
) -> None:
    problem = RuntimeUnavailableError(
        message,
        runtime="xtr",
        detail=detail,
        cause=cause,
    ).to_problem_details(instance=PROBLEM_INSTANCE)
    typer.echo(json.dumps(problem, indent=2), err=False)
    raise typer.Exit(code=1)


def main() -> None:  # pragma: no cover - Typer entrypoint
    """Execute the Typer CLI."""
    APP()


if __name__ == "__main__":  # pragma: no cover
    main()
