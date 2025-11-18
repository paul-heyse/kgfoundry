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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import click
import typer

from codeintel_rev.app import readiness as fs_readiness
from codeintel_rev.app.config_context import resolve_application_paths
from codeintel_rev.config.paths import ResolvedPaths
from codeintel_rev.config.settings import Settings, load_settings
from codeintel_rev.errors import RuntimeUnavailableError
from codeintel_rev.io.xtr_manager import XTRIndex

APP = typer.Typer(add_completion=False, no_args_is_help=True)
PROBLEM_INSTANCE = "/ops/runtime/xtr-open"
_VERBOSE_DEFAULT = False
_VERBOSE_FLAGS = ("--verbose", "-v")

# Type aliases for typer CLI parameters
_RootOption = Annotated[
    Path | None,
    typer.Option(
        "--root",
        help="Override the configured XTR artifact directory.",
    ),
]
_VerboseOption = Annotated[
    bool,
    typer.Option(
        *_VERBOSE_FLAGS,
        help="Pretty-print success payloads.",
    ),
]


@dataclass(slots=True, frozen=True)
class XtrOpenContext:
    """Dependency injection context for the xtr-open CLI."""

    settings_factory: Callable[[], Settings]
    paths_resolver: Callable[[Settings], ResolvedPaths]
    index_factory: Callable[[Path, Settings], XTRIndex]

    @classmethod
    def production(cls) -> XtrOpenContext:
        """Return the production CLI context.

        Returns
        -------
        XtrOpenContext
            Context configured with production factories.
        """
        return cls(
            settings_factory=load_settings,
            paths_resolver=resolve_application_paths,
            index_factory=lambda root, settings: XTRIndex(root, settings.xtr),
        )


_DEFAULT_CONTEXT = XtrOpenContext.production()


def _cli_context(ctx: typer.Context | None = None) -> XtrOpenContext:
    active = ctx or click.get_current_context(silent=True)
    if active is None:
        return _DEFAULT_CONTEXT
    state = active.ensure_object(dict)
    context = state.get("xtr_cli_context")
    if isinstance(context, XtrOpenContext):
        return context
    state["xtr_cli_context"] = _DEFAULT_CONTEXT
    return _DEFAULT_CONTEXT


@APP.command("xtr-open")
def xtr_open(
    root: _RootOption = None,
    *,
    verbose: _VerboseOption = _VERBOSE_DEFAULT,
) -> None:
    """Validate that XTR artifacts are present and readable.

    Extended Summary
    ----------------
    This CLI command performs a fail-fast probe for XTR (eXtended Token Retrieval)
    artifacts. It validates that the XTR index directory exists, can be opened,
    and is ready for use. The command is used for health checks and deployment
    validation. On success, it prints a JSON payload with readiness status and
    metadata (chunk count, token count, dimension, dtype). On failure, it exits
    with a non-zero code and prints RFC 9457 Problem Details.

    Parameters
    ----------
    root : _RootOption, optional
        Override the configured XTR artifact directory. If None (default), uses
        the directory resolved from application settings. Type alias for
        ``Annotated[Path | None, typer.Option(...)]`` for CLI option specification.
        Defaults to None.
    verbose : _VerboseOption, optional
        Pretty-print success payloads with indentation. When False (default),
        outputs compact JSON. Type alias for ``Annotated[bool, typer.Option(...)]``
        for CLI option specification. Defaults to False.

    Raises
    ------
    typer.Exit
        Raised by Typer to signal successful completion (code=0) or failure
        (code=1). On failure, the exit includes RFC 9457 Problem Details
        printed to stderr.

    Notes
    -----
    Time complexity O(1) for directory checks; O(I) for index opening where I
    is the cost of loading index metadata. The function performs filesystem I/O
    to validate paths and open the index. Thread-safe if called from a single
    process. The function is idempotent - multiple calls with the same inputs
    produce the same results.

    Examples
    --------
    >>> # Validate default XTR directory
    >>> xtr_open(root=None, verbose=False)
    {"ready": true, "limits": [], "metadata": {...}}

    >>> # Validate custom directory with verbose output
    >>> xtr_open(root=Path("/custom/xtr"), verbose=True)
    {
      "ready": true,
      "limits": [],
      "metadata": {
        "root": "/custom/xtr",
        "chunks": 1000,
        "tokens": 50000,
        "dim": 768,
        "dtype": "float32"
      }
    }
    """
    context = _cli_context()
    settings = context.settings_factory()
    paths = context.paths_resolver(settings)
    fs_readiness.raise_on_errors(fs_readiness.validate_paths(paths))
    xtr_root = root or paths.xtr_dir
    if root is not None and not root.is_dir():
        _exit_with_problem(
            "XTR artifacts unavailable",
            detail=f"Not a directory: {root}",
        )

    if not settings.xtr.enable:
        payload = {"ready": False, "limits": ["xtr disabled"]}
        typer.echo(json.dumps(payload, indent=2 if verbose else None))
        raise typer.Exit(code=0)

    if not xtr_root.exists():
        _exit_with_problem(
            "XTR artifacts unavailable",
            detail=f"Directory does not exist: {xtr_root}",
        )

    index = context.index_factory(xtr_root, settings)
    try:
        index.open()
    except (OSError, RuntimeError, ValueError) as exc:
        _exit_with_problem(
            "Failed to open XTR artifacts",
            detail=str(exc),
            cause=exc,
        )

    if not index.ready:
        _exit_with_problem("XTR artifacts loaded but not ready")

    metadata = index.metadata() or {}
    payload = {
        "ready": True,
        "limits": [],
        "metadata": {
            "root": str(xtr_root),
            "chunks": metadata.get("doc_count"),
            "tokens": metadata.get("total_tokens"),
            "dim": metadata.get("dim"),
            "dtype": metadata.get("dtype"),
        },
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
    problem["title"] = message
    typer.echo(json.dumps(problem), err=True)
    raise typer.Exit(code=1)


def main() -> None:  # pragma: no cover - Typer entrypoint
    """Execute the Typer CLI."""
    APP()


if __name__ == "__main__":  # pragma: no cover
    main()
