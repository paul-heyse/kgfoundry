"""Command-line interface for SPLADE artifact management."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import msgspec
import typer
from tools import CliContext, EnvelopeBuilder, cli_operation, sha256_file

from codeintel_rev.config.settings import load_settings
from codeintel_rev.io.splade_manager import (
    SpladeArtifactsManager,
    SpladeBenchmarkOptions,
    SpladeBuildOptions,
    SpladeEncodeOptions,
    SpladeEncoderService,
    SpladeExportOptions,
    SpladeIndexManager,
)

OptimizeFlag = Annotated[
    bool,
    typer.Option(
        "--optimize/--no-optimize",
        help="Enable Sentence-Transformers graph optimization.",
        show_default=True,
    ),
]
QuantizeFlag = Annotated[
    bool,
    typer.Option(
        "--quantize/--no-quantize",
        help="Produce a dynamically quantized ONNX artifact.",
        show_default=True,
    ),
]
OverwriteFlag = Annotated[
    bool,
    typer.Option(
        "--overwrite/--no-overwrite",
        help="Overwrite existing impact index contents when rebuilding.",
        show_default=True,
    ),
]

app = typer.Typer(
    help="SPLADE maintenance commands (artifacts, encoding, and impact indexes).",
    no_args_is_help=True,
    add_completion=False,
)


def _create_artifacts_manager() -> SpladeArtifactsManager:
    """Construct an artifacts manager using the active settings.

    Returns
    -------
    SpladeArtifactsManager
        Manager initialized with the current environment configuration.
    """
    return SpladeArtifactsManager(load_settings())


def _create_encoder_service() -> SpladeEncoderService:
    """Construct an encoder service using the active settings.

    Returns
    -------
    SpladeEncoderService
        Encoder service initialized with the current environment configuration.
    """
    return SpladeEncoderService(load_settings())


def _create_index_manager() -> SpladeIndexManager:
    """Construct an index manager using the active settings.

    Returns
    -------
    SpladeIndexManager
        Index manager initialized with the current environment configuration.
    """
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
QUANTIZATION_OPTION = typer.Option(
    "avx2",
    "--quantization-config",
    help="Sentence-Transformers quantization preset (e.g., avx2, avx512).",
)


@app.command("export-onnx")
def export_onnx(
    *,
    model_id: str | None = MODEL_ID_OPTION,
    optimize: OptimizeFlag = True,
    quantize: QuantizeFlag = True,
    quantization_config: str = QUANTIZATION_OPTION,
) -> None:
    """Export SPLADE ONNX artifacts (optimized and quantized)."""

    @cli_operation(echo_args=True, echo_env=True)
    def _run(
        ctx: CliContext,
        env: EnvelopeBuilder,
        *,
        options: SpladeExportOptions,
    ) -> None:
        manager = _create_artifacts_manager()
        summary = manager.export_onnx(options)

        metadata_path = Path(summary.metadata_path)
        _add_metadata_artifact(env, metadata_path)
        env.set_result(
            summary=f"Exported SPLADE ONNX artifacts to {summary.onnx_file}",
            payload={
                "onnx_file": summary.onnx_file,
                "metadata_path": summary.metadata_path,
                "optimized": options.optimize,
                "quantized": options.quantize,
            },
        )

        ctx.logger.info(
            "splade_export_onnx",
            extra={
                "onnx_file": summary.onnx_file,
                "metadata_path": summary.metadata_path,
                "optimize": options.optimize,
                "quantize": options.quantize,
            },
        )
        typer.echo(
            "[splade] Exported ONNX artifact "
            f"(file={summary.onnx_file}, metadata={summary.metadata_path})",
        )

    _run(
        options=SpladeExportOptions(
            model_id=model_id,
            optimize=optimize,
            quantize=quantize,
            quantization_config=quantization_config,
        ),
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


@app.command("encode")
def encode(
    *,
    source: Path = SOURCE_ARGUMENT,
    output_dir: Path | None = OUTPUT_DIR_OPTION,
    batch_size: int | None = BATCH_SIZE_OPTION,
    quantization: int | None = QUANTIZATION_OPTION_ENCODE,
    shard_size: int = SHARD_SIZE_OPTION,
) -> None:
    """Encode a corpus into SPLADE JsonVectorCollection shards."""

    @cli_operation(echo_args=True, echo_env=True)
    def _run(
        ctx: CliContext,
        env: EnvelopeBuilder,
        *,
        source: Path,
        options: SpladeEncodeOptions,
    ) -> None:
        service = _create_encoder_service()
        summary = service.encode_corpus(source, options)

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
        options=SpladeEncodeOptions(
            output_dir=output_dir,
            batch_size=batch_size,
            quantization=quantization,
            shard_size=shard_size,
        ),
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
QUERY_OPTION = typer.Option(
    None,
    "--query",
    "-q",
    help="Query text to benchmark.",
)
QUERIES_FILE_OPTION = typer.Option(
    None,
    "--queries-file",
    help="Path to a file containing one query per line.",
)
WARMUP_OPTION = typer.Option(
    3,
    "--warmup",
    min=0,
    help="Number of warm-up iterations before measuring latency.",
    show_default=True,
)
RUNS_OPTION = typer.Option(
    10,
    "--runs",
    min=1,
    help="Number of measured iterations for the benchmark.",
    show_default=True,
)


@app.command("build-index")
def build_index(
    *,
    vectors_dir: Path | None = VECTORS_DIR_OPTION,
    index_dir: Path | None = INDEX_DIR_OPTION,
    threads: int | None = THREADS_OPTION,
    max_clause_count: int | None = MAX_CLAUSE_OPTION,
    overwrite: OverwriteFlag = True,
) -> None:
    """Build a SPLADE Lucene impact index from JsonVectorCollection shards."""

    @cli_operation(echo_args=True, echo_env=True)
    def _run(
        ctx: CliContext,
        env: EnvelopeBuilder,
        *,
        options: SpladeBuildOptions,
    ) -> None:
        manager = _create_index_manager()
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
        options=SpladeBuildOptions(
            vectors_dir=vectors_dir,
            index_dir=index_dir,
            threads=threads,
            max_clause_count=max_clause_count,
            overwrite=overwrite,
        ),
    )


@app.command("bench")
def bench(
    *,
    query: str | None = QUERY_OPTION,
    queries_file: Path | None = QUERIES_FILE_OPTION,
    warmup: int = WARMUP_OPTION,
    runs: int = RUNS_OPTION,
) -> None:
    """Benchmark SPLADE query encoding latency.

    This command measures the performance of SPLADE query encoding by running
    multiple iterations of encoding operations and reporting statistical metrics
    (mean, p50, p95 latency). It supports benchmarking single queries or batches
    of queries from a file, with configurable warmup and measurement iterations
    to ensure accurate performance measurements.

    The benchmark initializes the SPLADE encoder service, performs warmup runs
    to stabilize performance (accounting for JIT compilation, cache warming, etc.),
    then executes measurement runs and calculates latency statistics. Results are
    displayed to stdout and logged with structured metadata.

    Parameters
    ----------
    query : str | None, optional
        Single query string to benchmark. If provided, this query is included in
        the benchmark set. Can be combined with queries_file to benchmark multiple
        queries. Defaults to None (no single query).
    queries_file : Path | None, optional
        Path to a text file containing one query per line. All non-empty lines
        are read and included in the benchmark. Can be combined with query to
        benchmark both. Defaults to None (no file queries).
    warmup : int, optional
        Number of warmup iterations to perform before measurement. Warmup runs
        help stabilize performance by allowing JIT compilation, cache warming,
        and other one-time optimizations to complete. Defaults to the value from
        WARMUP_OPTION constant.
    runs : int, optional
        Number of measurement iterations to perform after warmup. These runs
        are used to calculate latency statistics (mean, p50, p95). More runs
        provide more accurate statistics but take longer. Defaults to the value
        from RUNS_OPTION constant.

    Raises
    ------
    typer.BadParameter
        If no queries are provided (both query and queries_file are None/empty)
        or if the queries_file path exists but is invalid/unreadable.
    """
    query_values: list[str] = []
    if query:
        query_values.append(query)

    if queries_file is not None:
        file_path = queries_file
        if not file_path.exists():
            message = f"Queries file {file_path} does not exist."
            raise typer.BadParameter(message, param_hint="--queries-file")
        file_queries = [
            line.strip()
            for line in file_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        query_values.extend(file_queries)

    if not query_values:
        message = "Provide --query or --queries-file with at least one query."
        raise typer.BadParameter(message, param_hint="--query")

    @cli_operation(echo_args=True, echo_env=True)
    def _run(
        ctx: CliContext,
        env: EnvelopeBuilder,
        *,
        queries: tuple[str, ...],
        options: SpladeBenchmarkOptions,
    ) -> None:
        service = _create_encoder_service()
        summary = service.benchmark_queries(list(queries), options)

        env.set_result(
            summary=(
                f"Benchmarked {summary.query_count} queries "
                f"(runs={summary.measure_iterations}, warmup={summary.warmup_iterations})"
            ),
            payload=msgspec.to_builtins(summary),
        )
        ctx.logger.info(
            "splade_benchmark",
            extra={
                "query_count": summary.query_count,
                "warmup_iterations": summary.warmup_iterations,
                "measure_iterations": summary.measure_iterations,
                "p50_ms": summary.p50_latency_ms,
                "p95_ms": summary.p95_latency_ms,
                "provider": summary.provider,
            },
        )
        typer.echo(
            "[splade] Benchmark latency "
            f"(p50={summary.p50_latency_ms:.2f} ms, p95={summary.p95_latency_ms:.2f} ms, "
            f"mean={summary.mean_latency_ms:.2f} ms)",
        )

    _run(
        queries=tuple(query_values),
        options=SpladeBenchmarkOptions(
            warmup_iterations=warmup,
            measure_iterations=runs,
        ),
    )


def main() -> None:
    """Run the SPLADE CLI directly."""
    app()


if __name__ == "__main__":  # pragma: no cover - manual execution entrypoint
    main()
