"""Entry point aggregating CodeIntel CLI subcommands."""

from __future__ import annotations

import importlib
from types import ModuleType

import typer

app = typer.Typer(
    help="CodeIntel operational commands.",
    no_args_is_help=True,
    add_completion=False,
)


def _load_cli_module(path: str) -> ModuleType:
    """Import a CLI module lazily to avoid circular imports.

    This function dynamically imports a CLI module by its dotted path to avoid
    circular import issues during module initialization. The function uses
    importlib.import_module() to perform the import at runtime.

    Parameters
    ----------
    path : str
        Dotted module path to import (e.g., "codeintel_rev.cli.indexctl").
        The path must be a valid Python module path accessible from the current
        import context. Used to lazily load CLI command modules.

    Returns
    -------
    ModuleType
        Imported module object referenced by path. The module is loaded and
        cached by Python's import system. Subsequent calls with the same path
        return the cached module instance.
    """
    return importlib.import_module(path)


bm25_cli = _load_cli_module("codeintel_rev.cli.bm25")
indexctl_cli = _load_cli_module("codeintel_rev.cli.indexctl")
splade_cli = _load_cli_module("codeintel_rev.cli.splade")
xtr_cli = _load_cli_module("codeintel_rev.cli.xtr")

app.add_typer(
    bm25_cli.app,
    name="bm25",
    help="BM25 corpus and index management commands.",
)
app.add_typer(
    indexctl_cli.app,
    name="indexctl",
    help="Index lifecycle management commands.",
)
app.add_typer(
    splade_cli.app,
    name="splade",
    help="SPLADE model and impact index management commands.",
)
app.add_typer(
    xtr_cli.app,
    name="xtr",
    help="XTR/WARP index management commands.",
)


def main() -> None:
    """Run the aggregated CodeIntel CLI."""
    app()


if __name__ == "__main__":  # pragma: no cover - manual execution entrypoint
    main()
