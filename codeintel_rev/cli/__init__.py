"""Entry point aggregating CodeIntel CLI subcommands."""

from __future__ import annotations

import typer

from codeintel_rev.cli import bm25, indexctl, splade, xtr

app = typer.Typer(
    help="CodeIntel operational commands.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(bm25.app, name="bm25", help="BM25 corpus and index management commands.")
app.add_typer(indexctl.app, name="indexctl", help="Index lifecycle management commands.")
app.add_typer(splade.app, name="splade", help="SPLADE model and impact index management commands.")
app.add_typer(xtr.app, name="xtr", help="XTR/WARP index management commands.")


def main() -> None:
    """Run the aggregated CodeIntel CLI."""
    app()


if __name__ == "__main__":  # pragma: no cover - manual execution entrypoint
    main()
