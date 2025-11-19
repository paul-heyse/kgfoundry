"""Entry point aggregating CodeIntel CLI subcommands."""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import TYPE_CHECKING

import typer

_LAZY_EXPORTS = {
    "enrich_analytics": "codeintel_rev.cli.enrich_analytics",
    "enrich_overlays": "codeintel_rev.cli.enrich_overlays",
    "enrich_pipeline": "codeintel_rev.cli.enrich_pipeline",
}


if TYPE_CHECKING:
    enrich_analytics: ModuleType
    enrich_overlays: ModuleType
    enrich_pipeline: ModuleType

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


def __getattr__(name: str) -> ModuleType:
    """Lazily import CLI helper modules on first access.

    This keeps ``python -m codeintel_rev.cli.<module>`` invocations import-clean
    by avoiding eager submodule imports during package initialization.

    Parameters
    ----------
    name : str
        Export requested via attribute access or ``from codeintel_rev.cli import``.

    Returns
    -------
    ModuleType
        The imported submodule referenced by ``name``.

    Raises
    ------
    AttributeError
        If the requested attribute is not a lazily-exported CLI module.
    """
    if name in _LAZY_EXPORTS:
        module = importlib.import_module(_LAZY_EXPORTS[name])
        globals()[name] = module
        return module
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    """Return module attributes including lazily exported submodules.

    Returns
    -------
    list[str]
        Sorted attribute names available on this module.
    """
    return sorted({*globals(), *_LAZY_EXPORTS})


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


__all__ = [
    "app",
    "enrich_analytics",
    "enrich_overlays",
    "enrich_pipeline",
    "main",
]


def main() -> None:
    """Run the aggregated CodeIntel CLI."""
    app()


if __name__ == "__main__":  # pragma: no cover - manual execution entrypoint
    main()
