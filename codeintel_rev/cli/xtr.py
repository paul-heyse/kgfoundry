"""CLI for building and verifying XTR token indexes."""

from __future__ import annotations

import typer

from codeintel_rev.app.config_context import resolve_application_paths
from codeintel_rev.config.settings import load_settings
from codeintel_rev.indexing.xtr_build import build_xtr_index
from codeintel_rev.io.xtr_manager import XTRIndex

app = typer.Typer(
    help="XTR/WARP maintenance commands.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command("build")
def build() -> None:
    """Build token-level XTR artifacts from the DuckDB catalog."""
    settings = load_settings()
    summary = build_xtr_index(settings)
    typer.echo(
        "XTR build complete "
        f"(chunks={summary.chunk_count}, tokens={summary.token_count}, dtype={summary.dtype})."
    )
    typer.echo(f" - tokens: {summary.token_path}")
    typer.echo(f" - metadata: {summary.meta_path}")


@app.command("verify")
def verify() -> None:
    """Verify that XTR artifacts can be opened.

    Raises
    ------
    typer.Exit
        Raised with exit code 1 when artifacts are missing.
    """
    settings = load_settings()
    paths = resolve_application_paths(settings)
    index = XTRIndex(paths.xtr_dir, settings.xtr)
    index.open()
    if not index.ready:
        typer.echo(
            f"XTR artifacts missing or unreadable at {paths.xtr_dir}.",
            err=True,
        )
        raise typer.Exit(code=1)
    meta = index.metadata() or {}
    typer.echo(
        "XTR ready: "
        f"chunks={meta.get('doc_count')} tokens={meta.get('total_tokens')} dim={meta.get('dim')}"
    )


def main() -> None:
    """Run the XTR CLI."""
    app()


if __name__ == "__main__":  # pragma: no cover - manual execution entrypoint
    main()
