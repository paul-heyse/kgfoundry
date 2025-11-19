"""Fail-fast probe for XTR artifacts."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import click
import typer

from codeintel_rev.app import readiness as fs_readiness
from codeintel_rev.app.config_context import resolve_application_paths
from codeintel_rev.config import AppConfig, load_app_config
from codeintel_rev.config.paths import ResolvedPaths
from codeintel_rev.io.xtr_manager import XTRIndex
from kgfoundry_common.errors import ConfigurationError

APP = typer.Typer(add_completion=False, no_args_is_help=True)
PROBLEM_INSTANCE = "/ops/runtime/xtr-open"
_VERBOSE_DEFAULT = False
_VERBOSE_FLAGS = ("--verbose", "-v")

_RootOption = Annotated[
    Path | None,
    typer.Option("--root", help="Override the configured XTR artifact directory."),
]
_VerboseOption = Annotated[
    bool,
    typer.Option(*_VERBOSE_FLAGS, help="Pretty-print success payloads."),
]


@dataclass(slots=True, frozen=True)
class XtrOpenContext:
    """Dependency injection context for the xtr-open CLI."""

    app_config_loader: Callable[[], AppConfig]
    paths_resolver: Callable[[AppConfig], ResolvedPaths]
    index_factory: Callable[[Path, AppConfig], XTRIndex]

    @classmethod
    def production(cls) -> XtrOpenContext:
        """Return the production CLI context.

        Returns
        -------
        XtrOpenContext
            Production context with default implementations for app config loading,
            paths resolution, and XTR index factory.
        """

        def _loader() -> AppConfig:
            return load_app_config(file=os.environ.get("CODEINTEL_CONFIG_FILE"))

        return cls(
            app_config_loader=_loader,
            paths_resolver=resolve_application_paths,
            index_factory=lambda root, cfg: XTRIndex(root, cfg.xtr),
        )


_DEFAULT_CONTEXT = XtrOpenContext.production()


def _cli_context(ctx: typer.Context | None = None) -> XtrOpenContext:
    """Retrieve or create CLI context from Typer/Click context.

    Parameters
    ----------
    ctx : typer.Context | None, optional
        Optional Typer context. If None, attempts to get the current context.
        Defaults to None.

    Returns
    -------
    XtrOpenContext
        Context attached to the Typer state or the default context.
    """
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

    Parameters
    ----------
    root : Path | None, optional
        Override the configured XTR artifact directory. If None, uses the configured
        directory from app config. Defaults to None.
    verbose : bool, optional
        Pretty-print success payloads. Defaults to False.

    Raises
    ------
    typer.Exit
        Exits with code 0 when XTR is disabled or artifacts are ready.
        Exits with code 1 when artifacts are unavailable or invalid.
    """
    context = _cli_context()
    app_config = context.app_config_loader()
    paths = context.paths_resolver(app_config)
    try:
        fs_readiness.raise_on_errors(fs_readiness.validate_paths(paths))
    except ConfigurationError as exc:
        _exit_with_problem(
            "Invalid repository configuration",
            detail=str(exc),
            cause=exc,
        )

    if not app_config.xtr.enable:
        payload = {"ready": False, "limits": ["xtr disabled"]}
        typer.echo(json.dumps(payload, indent=2 if verbose else None))
        raise typer.Exit(code=0)

    xtr_root = root or paths.xtr_dir
    if root is not None and not root.is_dir():
        _exit_with_problem(
            "XTR artifacts unavailable",
            detail=f"Not a directory: {root}",
        )
    if not xtr_root.exists():
        _exit_with_problem(
            "XTR artifacts unavailable",
            detail=f"Directory does not exist: {xtr_root}",
        )

    index = context.index_factory(xtr_root, app_config)
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
    title: str,
    *,
    detail: str | None = None,
    cause: Exception | None = None,
) -> None:
    """Emit RFC 9457 Problem Details payload and exit.

    Parameters
    ----------
    title : str
        Problem title string.
    detail : str | None, optional
        Optional detailed error message. Defaults to None.
    cause : Exception | None, optional
        Optional exception that caused the problem. Defaults to None.

    Raises
    ------
    typer.Exit
        Always exits with code 1, optionally chained from the cause exception.
    """
    payload = {
        "type": "https://kgfoundry.dev/problems/resource-unavailable",
        "title": title,
        "status": 503,
        "runtime": "xtr",
        "instance": PROBLEM_INSTANCE,
    }
    if detail:
        payload["detail"] = detail
    typer.echo(json.dumps(payload, indent=2), err=True)
    if cause is None:
        raise typer.Exit(code=1)
    raise typer.Exit(code=1) from cause


if __name__ == "__main__":  # pragma: no cover
    APP()
