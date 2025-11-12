"""CLI helpers for building Lucene indexes and flipping lifecycle pointers."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from codeintel_rev.config.settings import load_settings
from codeintel_rev.indexing.index_lifecycle import LuceneAssets, link_current_lucene
from codeintel_rev.io.bm25_manager import BM25BuildOptions, BM25IndexManager
from codeintel_rev.io.splade_manager import SpladeBuildOptions, SpladeIndexManager

JsonDirOption = Annotated[
    Path | None,
    typer.Option(
        "--jsonl-dir",
        "-j",
        help="JsonCollection directory (defaults to configured BM25 corpus directory).",
    ),
]
IndexDirOption = Annotated[
    Path | None,
    typer.Option(
        "--index-dir",
        "-i",
        help="Lucene index directory (defaults to the configured directory).",
    ),
]
VectorsDirOption = Annotated[
    Path | None,
    typer.Option(
        "--vectors-dir",
        "-v",
        help="JsonVectorCollection directory (defaults to configured SPLADE directory).",
    ),
]
ThreadsOption = Annotated[
    int | None,
    typer.Option(
        "--threads",
        "-t",
        min=1,
        help="Worker thread count for Pyserini (defaults to configuration).",
    ),
]
MaxClauseOption = Annotated[
    int | None,
    typer.Option(
        "--max-clause-count",
        "-m",
        min=1024,
        help="Override Lucene maxClauseCount (defaults to configured SPLADE setting).",
    ),
]
OverwriteFlag = Annotated[
    bool,
    typer.Option(
        "--overwrite/--no-overwrite",
        help="Overwrite the target directory when rebuilding.",
        show_default=True,
    ),
]
VersionArgument = Annotated[
    str,
    typer.Argument(help="Version identifier used for the lifecycle pointer."),
]
BaseDirOption = Annotated[
    Path,
    typer.Option(
        "--base-dir",
        help="Index lifecycle root directory (contains CURRENT pointer).",
        show_default="indexes",
    ),
]
Bm25DirOption = Annotated[
    Path | None,
    typer.Option("--bm25-dir", help="BM25 index directory to publish."),
]
SpladeDirOption = Annotated[
    Path | None,
    typer.Option("--splade-dir", help="SPLADE index directory to publish."),
]

app = typer.Typer(
    help="Utilities for building BM25/SPLADE indexes and publishing Lucene assets.",
    no_args_is_help=True,
    add_completion=False,
)


def _bm25_manager() -> BM25IndexManager:
    """Return a BM25 index manager configured from the active settings.

    Returns
    -------
    BM25IndexManager
        Manager initialised with the currently loaded settings.
    """
    return BM25IndexManager(load_settings())


def _splade_manager() -> SpladeIndexManager:
    """Return a SPLADE index manager configured from the active settings.

    Returns
    -------
    SpladeIndexManager
        Manager initialised with the currently loaded settings.
    """
    return SpladeIndexManager(load_settings())


@app.command("bm25")
def build_bm25_index(
    *,
    jsonl_dir: JsonDirOption = None,
    index_dir: IndexDirOption = None,
    threads: ThreadsOption = None,
    overwrite: OverwriteFlag = True,
) -> None:
    """Build a Lucene BM25 index with positional/docvector/raw storage enabled."""
    manager = _bm25_manager()
    options = BM25BuildOptions(
        json_dir=jsonl_dir,
        index_dir=index_dir,
        threads=threads,
        overwrite=overwrite,
        store_positions=True,
        store_docvectors=True,
        store_raw=True,
    )
    metadata = manager.build_index(options)
    typer.echo(
        f"[bm25] Built index at {metadata.index_dir} "
        f"(docs={metadata.doc_count}, size={metadata.index_size_bytes} bytes)",
    )


@app.command("splade-impact")
def build_splade_impact_index(
    *,
    vectors_dir: VectorsDirOption = None,
    index_dir: IndexDirOption = None,
    threads: ThreadsOption = None,
    max_clause_count: MaxClauseOption = None,
    overwrite: OverwriteFlag = True,
) -> None:
    """Build a SPLADE Lucene impact index from JsonVectorCollection shards."""
    manager = _splade_manager()
    options = SpladeBuildOptions(
        vectors_dir=vectors_dir,
        index_dir=index_dir,
        threads=threads,
        max_clause_count=max_clause_count,
        overwrite=overwrite,
    )
    metadata = manager.build_index(options)
    typer.echo(
        f"[splade] Built impact index at {metadata.index_dir} "
        f"(docs={metadata.doc_count}, size={metadata.index_size_bytes} bytes)",
    )


@app.command("publish")
def publish_lucene_assets(
    version: VersionArgument,
    base_dir: BaseDirOption = Path("indexes"),
    bm25_dir: Bm25DirOption = None,
    splade_dir: SpladeDirOption = None,
) -> None:
    """Copy Lucene assets into the lifecycle root and flip the CURRENT pointer."""
    assets = LuceneAssets(
        bm25_dir=bm25_dir.resolve() if bm25_dir is not None else None,
        splade_dir=splade_dir.resolve() if splade_dir is not None else None,
    )
    link_current_lucene(base_dir.resolve(), version, assets)
    typer.echo(
        "[publish] Published Lucene assets "
        f"(bm25={'yes' if bm25_dir else 'no'}, splade={'yes' if splade_dir else 'no'}) "
        f"to version {version}",
    )


def main() -> None:
    """Execute the build_indexes CLI."""
    app()


if __name__ == "__main__":  # pragma: no cover - manual execution entrypoint
    main()
