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

# Type aliases for CLI parameters to help pydoclint parse Annotated types correctly
_QueryArg = Annotated[str, typer.Argument(help="Natural language query.")]
_KOption = Annotated[int, typer.Option("--k", "-k", min=1, help="Top-k documents to return.")]
_CandidateIdsOption = Annotated[
    list[int] | None,
    typer.Option("--candidate-id", "-c", help="Optional Stage-0 candidate ids to rescore."),
]
_ExplainOption = Annotated[bool | None, typer.Option(help="Include token-level attributions.")]


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
    query: _QueryArg,
    k: _KOption = 5,
    candidate_ids: _CandidateIdsOption = None,
    explain: _ExplainOption = None,
) -> None:
    """Run a quick XTR search (wide or narrow depending on candidate ids).

    Extended Summary
    ----------------
    This CLI command performs XTR-based semantic search, supporting both wide-mode
    (index-wide search) and narrow-mode (rescoring Stage-0 candidates) depending on
    whether candidate_ids are provided. It loads the XTR index, executes the search,
    and prints results to stdout. This is a utility command for testing and debugging
    XTR search functionality outside of the main MCP server.

    Parameters
    ----------
    query : _QueryArg
        Natural language query string to search for. Will be encoded into token
        embeddings and used for MaxSim computation against the XTR index.
        Type alias for ``Annotated[str, typer.Argument(...)]`` for CLI argument
        specification. Provided as a positional argument via typer.
    k : _KOption, optional
        Maximum number of top-k documents to return. Must be at least 1.
        Defaults to 5. Type alias for ``Annotated[int, typer.Option(...)]`` for
        CLI option specification. Provided as an option via typer (--k, -k).
    candidate_ids : _CandidateIdsOption, optional
        Optional list of Stage-0 candidate chunk IDs to rescore. If provided,
        performs narrow-mode rescoring on these candidates only. If None, performs
        wide-mode search across all chunks. Defaults to None. Type alias for
        ``Annotated[list[int] | None, typer.Option(...)]`` for CLI option
        specification. Provided as an option via typer (--candidate-id, -c).
    explain : _ExplainOption, optional
        Whether to include token-level attribution information in results. If True,
        includes explainability data showing token alignments. If None, defaults
        to True (explainability enabled). Type alias for
        ``Annotated[bool | None, typer.Option(...)]`` for CLI option specification.
        Provided as an option via typer.

    Raises
    ------
    typer.Exit
        If XTR artifacts are missing and the command cannot run. This occurs when
        the XTR index has not been built or is not ready for search operations.

    Notes
    -----
    Time complexity depends on search mode: O(N * T * D) for wide-mode where N is
    total chunks, T is tokens per chunk, D is embedding dimension; O(C * T * D) for
    narrow-mode where C is candidate count. Space complexity O(k) for results.
    The function performs file I/O to load the XTR index and GPU/CPU computation
    for encoding and scoring. Not thread-safe due to index loading.
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
