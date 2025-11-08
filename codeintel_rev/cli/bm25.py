"""Command-line interface for BM25 corpus preparation and index builds."""

from __future__ import annotations

from pathlib import Path

import typer
from tools import CliContext, EnvelopeBuilder, cli_operation, sha256_file

from codeintel_rev.config.settings import load_settings
from codeintel_rev.io.bm25_manager import BM25BuildOptions, BM25IndexManager

app = typer.Typer(
    help="BM25 maintenance commands (corpus preparation and index builds).",
    no_args_is_help=True,
    add_completion=False,
)


def _create_bm25_manager() -> BM25IndexManager:
    """Return an index manager configured from environment settings.

    Returns
    -------
    BM25IndexManager
        Manager using the active environment configuration.
    """
    return BM25IndexManager(load_settings())


def _add_metadata_artifact(env: EnvelopeBuilder, path: Path) -> None:
    """Attach metadata artifact information to the CLI envelope."""
    if path.exists():
        env.add_artifact(kind="json", path=path, digest=sha256_file(path))


SOURCE_ARGUMENT = typer.Argument(
    ...,
    help="Path to the JSONL corpus file.",
)
OVERWRITE_DEFAULT = True
OUTPUT_DIR_OPTION = typer.Option(
    None,
    "--output-dir",
    "-o",
    help="Directory for JsonCollection output (defaults to configured BM25 corpus directory).",
)
OVERWRITE_OPTION = typer.Option(
    OVERWRITE_DEFAULT,
    "--overwrite/--no-overwrite",
    help="Overwrite existing JsonCollection files when preparing the corpus.",
    show_default=True,
)


@app.command("prepare-corpus")
def prepare_corpus(
    *,
    source: Path = SOURCE_ARGUMENT,
    output_dir: Path | None = OUTPUT_DIR_OPTION,
    overwrite: bool = OVERWRITE_OPTION,
) -> None:
    """Prepare a BM25 JsonCollection from a JSONL source."""

    @cli_operation(echo_args=True, echo_env=True)
    def _run(
        ctx: CliContext,
        env: EnvelopeBuilder,
        *,
        source: Path,
        output_dir: Path | None,
        overwrite: bool,
    ) -> None:
        manager = _create_bm25_manager()
        summary = manager.prepare_corpus(source, output_dir=output_dir, overwrite=overwrite)

        metadata_path = Path(summary.corpus_metadata_path)
        _add_metadata_artifact(env, metadata_path)
        env.set_result(
            summary=f"Prepared {summary.doc_count} documents.",
            payload={
                "doc_count": summary.doc_count,
                "output_dir": summary.output_dir,
                "metadata_path": summary.corpus_metadata_path,
                "digest": summary.digest,
            },
        )

        ctx.logger.info(
            "bm25_prepare_corpus",
            extra={
                "doc_count": summary.doc_count,
                "output_dir": summary.output_dir,
                "metadata_path": summary.corpus_metadata_path,
            },
        )
        typer.echo(
            f"[bm25] Prepared {summary.doc_count} documents into {summary.output_dir} "
            f"(metadata: {summary.corpus_metadata_path})",
        )

    _run(source=source, output_dir=output_dir, overwrite=overwrite)


JSON_DIR_OPTION = typer.Option(
    None,
    "--json-dir",
    "-j",
    help="JsonCollection directory to index (defaults to configured BM25 corpus directory).",
)
INDEX_DIR_OPTION = typer.Option(
    None,
    "--index-dir",
    "-i",
    help="Target Lucene index directory (defaults to configured BM25 index directory).",
)
THREADS_OPTION = typer.Option(
    None,
    "--threads",
    "-t",
    min=1,
    help="Worker thread count for Pyserini (defaults to configured BM25 configuration).",
)


@app.command("build-index")
def build_index(
    *,
    json_dir: Path | None = JSON_DIR_OPTION,
    index_dir: Path | None = INDEX_DIR_OPTION,
    threads: int | None = THREADS_OPTION,
) -> None:
    """Build a Lucene BM25 index using Pyserini."""

    @cli_operation(echo_args=True, echo_env=True)
    def _run(
        ctx: CliContext,
        env: EnvelopeBuilder,
        *,
        json_dir: Path | None,
        index_dir: Path | None,
        threads: int | None,
    ) -> None:
        manager = _create_bm25_manager()
        options = BM25BuildOptions(
            json_dir=json_dir,
            index_dir=index_dir,
            threads=threads,
        )
        metadata = manager.build_index(options)

        metadata_path = Path(metadata.index_dir) / "metadata.json"
        _add_metadata_artifact(env, metadata_path)
        env.set_result(
            summary=f"Built BM25 index with {metadata.doc_count} documents.",
            payload={
                "doc_count": metadata.doc_count,
                "index_dir": metadata.index_dir,
                "threads": metadata.threads,
                "corpus_digest": metadata.corpus_digest,
                "pyserini_version": metadata.pyserini_version,
                "index_size_bytes": metadata.index_size_bytes,
            },
        )

        ctx.logger.info(
            "bm25_build_index",
            extra={
                "doc_count": metadata.doc_count,
                "index_dir": metadata.index_dir,
                "threads": metadata.threads,
                "index_size_bytes": metadata.index_size_bytes,
            },
        )
        typer.echo(
            f"[bm25] Built index at {metadata.index_dir} "
            f"(docs={metadata.doc_count}, size={metadata.index_size_bytes} bytes)",
        )

    _run(json_dir=json_dir, index_dir=index_dir, threads=threads)


def main() -> None:
    """Run the BM25 CLI directly."""
    app()


if __name__ == "__main__":  # pragma: no cover - manual execution entrypoint
    main()
