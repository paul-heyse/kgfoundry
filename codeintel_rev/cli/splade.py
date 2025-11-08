"""Command-line interface for SPLADE artifact management."""

from __future__ import annotations

from pathlib import Path

import typer
from tools import CliContext, EnvelopeBuilder, cli_operation, sha256_file

from codeintel_rev.config.settings import load_settings
from codeintel_rev.io.splade_manager import (
    SpladeArtifactsManager,
    SpladeBuildOptions,
    SpladeEncoderService,
    SpladeIndexManager,
)

app = typer.Typer(
    help="SPLADE maintenance commands (artifacts, encoding, and impact indexes).",
    no_args_is_help=True,
    add_completion=False,
)


def _create_artifacts_manager() -> SpladeArtifactsManager:
    """Return an artifacts manager using the active settings."""
    return SpladeArtifactsManager(load_settings())


def _create_encoder_service() -> SpladeEncoderService:
    """Return an encoder service using the active settings."""
    return SpladeEncoderService(load_settings())


def _create_index_manager() -> SpladeIndexManager:
    """Return an index manager using the active settings."""
    return SpladeIndexManager(load_settings())


def _add_metadata_artifact(env: EnvelopeBuilder, path: Path) -> None:
    """Attach metadata artifacts to CLI envelopes when available."""
    if path.exists():
        env.add_artifact(kind="json", path=path, digest=sha256_file(path))


MODEL_ID_OPTION = typer.Option(
    None,
    "--model-id",
    help="Override the configured SPLADE model identifier.",
)
PROVIDER_OPTION = typer.Option(
    None,
    "--provider",
    help="Execution provider used during export or encoding (defaults to configuration).",
)
FILE_NAME_OPTION = typer.Option(
    None,
    "--file-name",
    help="Custom ONNX file name to write (defaults to configured SPLADE_ONNX_FILE).",
)
OPTIMIZE_OPTION = typer.Option(
    True,
    "--optimize/--no-optimize",
    help="Enable Sentence-Transformers graph optimization.",
    show_default=True,
)
QUANTIZE_OPTION = typer.Option(
    True,
    "--quantize/--no-quantize",
    help="Produce a dynamically quantized ONNX artifact.",
    show_default=True,
)
QUANTIZATION_OPTION = typer.Option(
    "avx2",
    "--quantization-config",
    help="Sentence-Transformers quantization preset (e.g., avx2, avx512).",
)


@app.command("export-onnx")
def export_onnx(
    *,
    model_id: str | None = MODEL_ID_OPTION,
    provider: str | None = PROVIDER_OPTION,
    file_name: str | None = FILE_NAME_OPTION,
    optimize: bool = OPTIMIZE_OPTION,
    quantize: bool = QUANTIZE_OPTION,
    quantization_config: str = QUANTIZATION_OPTION,
) -> None:
    """Export SPLADE ONNX artifacts (optimized and quantized)."""

    @cli_operation(echo_args=True, echo_env=True)
    def _run(
        ctx: CliContext,
        env: EnvelopeBuilder,
        *,
        model_id: str | None,
        provider: str | None,
        file_name: str | None,
        optimize: bool,
        quantize: bool,
        quantization_config: str,
    ) -> None:
        manager = _create_artifacts_manager()
        summary = manager.export_onnx(
            model_id=model_id,
            provider=provider,
            file_name=file_name,
            optimize=optimize,
            quantize=quantize,
            quantization_config=quantization_config,
        )

        metadata_path = Path(summary.metadata_path)
        _add_metadata_artifact(env, metadata_path)
        env.set_result(
            summary=f"Exported SPLADE ONNX artifacts to {summary.onnx_file}",
            payload={
                "onnx_file": summary.onnx_file,
                "metadata_path": summary.metadata_path,
                "optimized": optimize,
                "quantized": quantize,
            },
        )

        ctx.logger.info(
            "splade_export_onnx",
            extra={
                "onnx_file": summary.onnx_file,
                "metadata_path": summary.metadata_path,
                "optimize": optimize,
                "quantize": quantize,
            },
        )
        typer.echo(
            "[splade] Exported ONNX artifact "
            f"(file={summary.onnx_file}, metadata={summary.metadata_path})",
        )

    _run(
        model_id=model_id,
        provider=provider,
        file_name=file_name,
        optimize=optimize,
        quantize=quantize,
        quantization_config=quantization_config,
    )


SOURCE_ARGUMENT = typer.Argument(
    ...,
    help="Path to the JSONL corpus with `id` and `contents`/`text` fields.",
)
OUTPUT_DIR_OPTION = typer.Option(
    None,
    "--output-dir",
    "-o",
    help="Directory for JsonVectorCollection output (defaults to configured directory).",
)
BATCH_SIZE_OPTION = typer.Option(
    None,
    "--batch-size",
    "-b",
    min=1,
    help="Batch size used during encoding (defaults to configured SPLADE batch size).",
)
QUANTIZATION_OPTION_ENCODE = typer.Option(
    None,
    "--quantization",
    "-q",
    min=1,
    help="Integer quantization factor for token impacts (defaults to configuration).",
)
SHARD_SIZE_OPTION = typer.Option(
    100_000,
    "--shard-size",
    min=1,
    help="Maximum documents per JsonVectorCollection shard before rotating.",
    show_default=True,
)
ONNX_FILE_OPTION = typer.Option(
    None,
    "--onnx-file",
    help="Specific ONNX file name to load relative to the configured ONNX directory.",
)


@app.command("encode")
def encode(
    *,
    source: Path = SOURCE_ARGUMENT,
    output_dir: Path | None = OUTPUT_DIR_OPTION,
    batch_size: int | None = BATCH_SIZE_OPTION,
    quantization: int | None = QUANTIZATION_OPTION_ENCODE,
    shard_size: int = SHARD_SIZE_OPTION,
    provider: str | None = PROVIDER_OPTION,
    onnx_file: str | None = ONNX_FILE_OPTION,
) -> None:
    """Encode a corpus into SPLADE JsonVectorCollection shards."""

    @cli_operation(echo_args=True, echo_env=True)
    def _run(
        ctx: CliContext,
        env: EnvelopeBuilder,
        *,
        source: Path,
        output_dir: Path | None,
        batch_size: int | None,
        quantization: int | None,
        shard_size: int,
        provider: str | None,
        onnx_file: str | None,
    ) -> None:
        service = _create_encoder_service()
        summary = service.encode_corpus(
            source,
            output_dir=output_dir,
            batch_size=batch_size,
            quantization=quantization,
            shard_size=shard_size,
            provider=provider,
            onnx_file=onnx_file,
        )

        metadata_path = Path(summary.metadata_path)
        _add_metadata_artifact(env, metadata_path)
        env.set_result(
            summary=f"Encoded {summary.doc_count} documents into {summary.vectors_dir}",
            payload={
                "doc_count": summary.doc_count,
                "vectors_dir": summary.vectors_dir,
                "metadata_path": summary.metadata_path,
                "shard_count": summary.shard_count,
            },
        )

        ctx.logger.info(
            "splade_encode_corpus",
            extra={
                "doc_count": summary.doc_count,
                "vectors_dir": summary.vectors_dir,
                "shard_count": summary.shard_count,
            },
        )
        typer.echo(
            "[splade] Encoded corpus "
            f"(docs={summary.doc_count}, shards={summary.shard_count}, "
            f"metadata={summary.metadata_path})",
        )

    _run(
        source=source,
        output_dir=output_dir,
        batch_size=batch_size,
        quantization=quantization,
        shard_size=shard_size,
        provider=provider,
        onnx_file=onnx_file,
    )


VECTORS_DIR_OPTION = typer.Option(
    None,
    "--vectors-dir",
    "-v",
    help="Directory containing JsonVectorCollection shards.",
)
INDEX_DIR_OPTION = typer.Option(
    None,
    "--index-dir",
    "-i",
    help="Lucene impact index output directory.",
)
THREADS_OPTION = typer.Option(
    None,
    "--threads",
    "-t",
    min=1,
    help="Worker threads for Pyserini (defaults to configured SPLADE threads).",
)
MAX_CLAUSE_OPTION = typer.Option(
    None,
    "--max-clause-count",
    "-c",
    min=1,
    help="Override Lucene Boolean clause limit (defaults to configuration).",
)
OVERWRITE_OPTION = typer.Option(
    True,
    "--overwrite/--no-overwrite",
    help="Overwrite existing impact index contents when rebuilding.",
    show_default=True,
)


@app.command("build-index")
def build_index(
    *,
    vectors_dir: Path | None = VECTORS_DIR_OPTION,
    index_dir: Path | None = INDEX_DIR_OPTION,
    threads: int | None = THREADS_OPTION,
    max_clause_count: int | None = MAX_CLAUSE_OPTION,
    overwrite: bool = OVERWRITE_OPTION,
) -> None:
    """Build a SPLADE Lucene impact index from JsonVectorCollection shards."""

    @cli_operation(echo_args=True, echo_env=True)
    def _run(
        ctx: CliContext,
        env: EnvelopeBuilder,
        *,
        vectors_dir: Path | None,
        index_dir: Path | None,
        threads: int | None,
        max_clause_count: int | None,
        overwrite: bool,
    ) -> None:
        manager = _create_index_manager()
        options = SpladeBuildOptions(
            vectors_dir=vectors_dir,
            index_dir=index_dir,
            threads=threads,
            max_clause_count=max_clause_count,
            overwrite=overwrite,
        )
        metadata = manager.build_index(options)

        metadata_path = Path(metadata.index_dir) / "metadata.json"
        _add_metadata_artifact(env, metadata_path)
        env.set_result(
            summary=f"Built SPLADE impact index at {metadata.index_dir}",
            payload={
                "doc_count": metadata.doc_count,
                "index_dir": metadata.index_dir,
                "vectors_dir": metadata.vectors_dir,
                "threads": metadata.threads,
                "pyserini_version": metadata.pyserini_version,
                "index_size_bytes": metadata.index_size_bytes,
            },
        )

        ctx.logger.info(
            "splade_build_index",
            extra={
                "doc_count": metadata.doc_count,
                "index_dir": metadata.index_dir,
                "threads": metadata.threads,
                "index_size_bytes": metadata.index_size_bytes,
            },
        )
        typer.echo(
            "[splade] Built impact index "
            f"(docs={metadata.doc_count}, size={metadata.index_size_bytes} bytes, "
            f"metadata={metadata_path})",
        )

    _run(
        vectors_dir=vectors_dir,
        index_dir=index_dir,
        threads=threads,
        max_clause_count=max_clause_count,
        overwrite=overwrite,
    )


def main() -> None:
    """Run the SPLADE CLI directly."""
    app()


if __name__ == "__main__":  # pragma: no cover - manual execution entrypoint
    main()

