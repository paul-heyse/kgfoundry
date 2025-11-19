"""Command-line interface for BM25 corpus preparation and index builds."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import click
import typer
from tools import CliContext, EnvelopeBuilder, cli_operation, sha256_file

from codeintel_rev.config import load_app_config
from codeintel_rev.config.api import AppConfig
from codeintel_rev.io.bm25_manager import BM25BuildOptions, BM25IndexManager


@dataclass(slots=True, frozen=True)
class BM25CliContext:
    """Dependency injection context for BM25 CLI operations."""

    manager_factory: Callable[[], BM25IndexManager]

    @classmethod
    def production(cls) -> BM25CliContext:
        """Return the production CLI context.

        Returns
        -------
        BM25CliContext
            Context configured with the default manager factory.
        """
        return cls(manager_factory=_default_bm25_manager_factory)


@lru_cache(maxsize=1)
def _cached_app_config() -> AppConfig:
    """Load and cache AppConfig for CLI invocations.

    Returns
    -------
    AppConfig
        Cached immutable configuration derived from env/file sources.
    """
    return load_app_config(file=os.environ.get("CODEINTEL_CONFIG_FILE"))


def _default_bm25_manager_factory() -> BM25IndexManager:
    """Return the default BM25 manager.

    Returns
    -------
    BM25IndexManager
        Manager configured from the active settings.
    """
    return BM25IndexManager(_cached_app_config())


app = typer.Typer(
    help="BM25 maintenance commands (corpus preparation and index builds).",
    no_args_is_help=True,
    add_completion=False,
)
_DEFAULT_CONTEXT = BM25CliContext.production()


def _cli_context(ctx: typer.Context | None = None) -> BM25CliContext:
    """Retrieve or create the BM25 CLI context from Typer state.

    Parameters
    ----------
    ctx : typer.Context | None, optional
        Typer context object. If None, attempts to retrieve the current Click
        context. Defaults to None.

    Returns
    -------
    BM25CliContext
        CLI context instance from Typer state, or the default production context
        if no context is available or configured.
    """
    active = ctx or click.get_current_context(silent=True)
    if active is None:
        return _DEFAULT_CONTEXT
    state = active.ensure_object(dict)
    context = state.get("bm25_cli_context")
    if isinstance(context, BM25CliContext):
        return context
    state["bm25_cli_context"] = _DEFAULT_CONTEXT
    return _DEFAULT_CONTEXT


@app.callback()
def bm25_callback(ctx: typer.Context) -> None:
    """Ensure CLI context defaults are configured."""
    state = ctx.ensure_object(dict)
    state.setdefault("bm25_cli_context", _DEFAULT_CONTEXT)


def _create_bm25_manager() -> BM25IndexManager:
    """Return an index manager configured from environment settings.

    Returns
    -------
    BM25IndexManager
        Index manager built from the active CLI context.
    """
    return _cli_context().manager_factory()


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
        """Execute the corpus preparation operation.

        Parameters
        ----------
        ctx : CliContext
            CLI context providing logging and operation tracking.
        env : EnvelopeBuilder
            Envelope builder for attaching artifacts and result metadata.
        source : Path
            Path to the JSONL corpus file to process.
        output_dir : Path | None
            Optional output directory for JsonCollection files. If None, uses
            the configured BM25 corpus directory.
        overwrite : bool
            Whether to overwrite existing JsonCollection files if they exist.
        """
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
        """Execute the BM25 index build operation.

        Parameters
        ----------
        ctx : CliContext
            CLI context providing logging and operation tracking.
        env : EnvelopeBuilder
            Envelope builder for attaching artifacts and result metadata.
        json_dir : Path | None
            Optional JsonCollection directory to index. If None, uses the
            configured BM25 corpus directory.
        index_dir : Path | None
            Optional target Lucene index directory. If None, uses the configured
            BM25 index directory.
        threads : int | None
            Optional worker thread count for Pyserini. If None, uses the
            configured BM25 thread count.
        """
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
