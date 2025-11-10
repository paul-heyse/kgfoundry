"""Typer CLI for building, verifying, and probing XTR artifacts."""

from __future__ import annotations

from typing import Annotated

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
        If artifacts are missing or unreadable.
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


@app.command("search")
def search(
    query: Annotated[str, typer.Argument(help="Natural language query.")],
    k: Annotated[int, typer.Option("--k", "-k", min=1, help="Top-k documents to return.")] = 5,
    candidate_ids: Annotated[
        list[int] | None,
        typer.Option("--candidate-id", "-c", help="Optional Stage-0 candidate ids to rescore."),
    ] = None,
    explain: Annotated[bool | None, typer.Option(help="Include token-level attributions.")] = None,
) -> None:
    """Run a quick XTR search (wide or narrow depending on candidate ids).

    Raises
    ------
    typer.Exit
        If artifacts are missing and the command cannot run.
    """
    settings = load_settings()
    paths = resolve_application_paths(settings)
    index = XTRIndex(paths.xtr_dir, settings.xtr)
    index.open()
    if not index.ready:
        typer.echo("XTR artifacts not ready; run `xtr build` first.", err=True)
        raise typer.Exit(code=1)

    include_explain = True if explain is None else explain
    if candidate_ids:
        hits = index.rescore(
            query=query,
            candidate_chunk_ids=candidate_ids,
            explain=include_explain,
        )
    else:
        hits = index.search(query=query, k=k, explain=include_explain)

    if not hits:
        typer.echo("No hits returned.")
        return
    typer.echo(f"Top {min(k, len(hits))} hits for query: {query!r}")
    for rank, (chunk_id, score, payload) in enumerate(hits[:k], start=1):
        typer.echo(f"[{rank}] chunk_id={chunk_id} score={score:.4f}")
        if include_explain and payload:
            matches = payload.get("token_matches") or []
            preview = ", ".join(
                f"(q={match['q_index']} doc={match['doc_index']} sim={match['similarity']:.3f})"
                for match in matches
            )
            if preview:
                typer.echo(f"    tokens: {preview}")


def main() -> None:
    """Execute the Typer app."""
    app()


if __name__ == "__main__":  # pragma: no cover - manual execution entrypoint
    main()
