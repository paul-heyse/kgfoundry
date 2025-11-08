"""SPLADE artifact management, encoding, and Lucene impact index builders."""

from __future__ import annotations

import importlib
import json
import logging
import math
import os
import shutil
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

import msgspec

from codeintel_rev.io.path_utils import resolve_within_repo
from kgfoundry_common.subprocess_utils import run_subprocess

if TYPE_CHECKING:
    from typing import Protocol

    from codeintel_rev.config.settings import Settings

    class _SparseEncoderProtocol(Protocol):
        def encode_document(self, sentences: Sequence[str]) -> Sequence[object]: ...

        def decode(
            self,
            embeddings: object,
            top_k: int | None = None,
        ) -> Sequence[Sequence[tuple[str, float]]]: ...

    class _OptimizerFunction(Protocol):
        def __call__(
            self,
            model: Any,
            *,
            optimization_config: str,
            model_name_or_path: str,
            push_to_hub: bool,
            create_pr: bool,
        ) -> None: ...

    class _QuantizerFunction(Protocol):
        def __call__(
            self,
            model: Any,
            *,
            quantization_config: str | None,
            model_name_or_path: str,
            push_to_hub: bool,
            create_pr: bool,
        ) -> None: ...


try:  # pragma: no cover - optional dependency
    from sentence_transformers import SparseEncoder
except ImportError:  # pragma: no cover - handled at runtime
    SparseEncoder = None  # type: ignore[misc]

try:  # pragma: no cover - optional dependency
    from sentence_transformers import (
        export_dynamic_quantized_onnx_model,
        export_optimized_onnx_model,
    )
except ImportError:  # pragma: no cover - handled at runtime
    export_dynamic_quantized_onnx_model = None  # type: ignore[misc]
    export_optimized_onnx_model = None  # type: ignore[misc]


GENERATOR_NAME = "codeintel_rev.io.splade_manager"
ARTIFACT_METADATA_FILENAME = "artifacts.json"
ENCODING_METADATA_FILENAME = "vectors_metadata.json"
INDEX_METADATA_FILENAME = "metadata.json"


logger = logging.getLogger(__name__)


class SpladeArtifactMetadata(msgspec.Struct, frozen=True):
    """Metadata describing exported SPLADE ONNX artifacts."""

    model_id: str
    model_dir: str
    onnx_dir: str
    onnx_file: str
    provider: str
    optimized: bool
    quantized: bool
    quantization_config: str | None
    exported_at: str
    generator: str


class SpladeExportSummary(msgspec.Struct, frozen=True):
    """Summary returned after exporting SPLADE artifacts."""

    onnx_file: str
    metadata_path: str


class SpladeEncodingMetadata(msgspec.Struct, frozen=True):
    """Metadata describing SPLADE vector encoding runs."""

    doc_count: int
    shard_count: int
    quantization: int
    batch_size: int
    provider: str
    vectors_dir: str
    source_path: str
    prepared_at: str
    generator: str


class SpladeEncodingSummary(msgspec.Struct, frozen=True):
    """Summary describing SPLADE encoding output."""

    doc_count: int
    vectors_dir: str
    metadata_path: str
    shard_count: int


class SpladeExportOptions(msgspec.Struct, frozen=True):
    """Options controlling SPLADE ONNX export behaviour."""

    model_id: str | None = None
    provider: str | None = None
    file_name: str | None = None
    optimize: bool = True
    quantize: bool = True
    quantization_config: str = "avx2"


class SpladeEncodeOptions(msgspec.Struct, frozen=True):
    """Options controlling SPLADE corpus encoding."""

    output_dir: str | Path | None = None
    batch_size: int | None = None
    quantization: int | None = None
    shard_size: int = 100_000
    provider: str | None = None
    onnx_file: str | None = None


class SpladeBuildOptions(msgspec.Struct, frozen=True):
    """Options controlling SPLADE Lucene impact index builds."""

    vectors_dir: str | Path | None = None
    index_dir: str | Path | None = None
    threads: int | None = None
    max_clause_count: int | None = None
    overwrite: bool = True


class SpladeIndexMetadata(msgspec.Struct, frozen=True):
    """Metadata describing a SPLADE Lucene impact index."""

    doc_count: int | None
    built_at: str
    vectors_dir: str
    corpus_digest: str | None
    pyserini_version: str
    threads: int
    index_dir: str
    index_size_bytes: int
    generator: str


@dataclass
class _ShardState:
    """Mutable encoding state for shard rotation."""

    vectors_dir: Path
    quantization: int
    shard_size: int
    doc_count: int = 0
    shard_index: int = 0
    shard_handle: TextIO | None = None
    shard_count: int = 0


@dataclass
class _ExportContext:
    """Context for SPLADE export operations."""

    model_id: str
    model_dir: Path
    onnx_dir: Path
    provider: str
    target_path: Path
    options: SpladeExportOptions


def _require_sparse_encoder() -> type:
    if SparseEncoder is None:  # pragma: no cover - defensive
        msg = (
            "sentence-transformers with SparseEncoder support is required for SPLADE "
            "operations. Install the 'sentence-transformers[onnx]' extra."
        )
        raise RuntimeError(msg)
    return SparseEncoder  # type: ignore[return-value]


def _require_export_helpers() -> tuple[_OptimizerFunction, _QuantizerFunction]:
    if export_optimized_onnx_model is None or export_dynamic_quantized_onnx_model is None:
        msg = (
            "SPLADE export helpers are unavailable. Upgrade sentence-transformers to a "
            "version providing export_optimized_onnx_model and "
            "export_dynamic_quantized_onnx_model."
        )
        raise RuntimeError(msg)
    return export_optimized_onnx_model, export_dynamic_quantized_onnx_model


def _write_struct(target: Path, payload: msgspec.Struct) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(msgspec.to_builtins(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _directory_size(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def _detect_pyserini_version() -> str:
    try:
        module = importlib.import_module("pyserini")
    except ModuleNotFoundError:  # pragma: no cover - fallback
        return "unknown"
    version = getattr(module, "__version__", None)
    return str(version) if version is not None else "unknown"


def _serialize_relative(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _quantize_tokens(pairs: Sequence[tuple[str, float]], quantization: int) -> dict[str, int]:
    vector: dict[str, int] = {}
    for token, weight in pairs:
        if weight <= 0:
            continue
        quantized = math.floor(weight * float(quantization) + 0.5)
        if quantized > 0:
            vector[token] = quantized
    return vector


def _iter_corpus(path: Path) -> Iterable[dict[str, object]]:
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            yield json.loads(line)


def _open_writer(vectors_dir: Path, index: int) -> tuple[Path, TextIO]:
    """Create a shard writer for the given shard index.

    Returns
    -------
    tuple[Path, TextIO]
        The shard path and an open text handle ready for writing.
    """
    shard_path = vectors_dir / f"part-{index:05d}.jsonl"
    return shard_path, shard_path.open("w", encoding="utf-8")


def _flush_batch(
    encoder: _SparseEncoderProtocol,
    batch: list[tuple[str, str]],
    state: _ShardState,
) -> None:
    """Encode and persist the current batch of documents.

    Raises
    ------
    RuntimeError
        If a shard handle unexpectedly becomes unavailable.
    """
    if not batch:
        return

    texts = [text for _, text in batch]
    embeddings = encoder.encode_document(texts)
    decoded = encoder.decode(embeddings, top_k=None)

    for (doc_id, _), token_pairs in zip(batch, decoded, strict=True):
        vector = _quantize_tokens(token_pairs, state.quantization)
        if state.shard_handle is None:
            _, handle = _open_writer(state.vectors_dir, state.shard_index)
            state.shard_handle = handle
            state.shard_count += 1
        handle = state.shard_handle
        if handle is None:  # pragma: no cover - defensive
            msg = "Shard handle unexpectedly missing during encoding."
            raise RuntimeError(msg)
        handle.write(
            json.dumps({"id": doc_id, "contents": "", "vector": vector}, ensure_ascii=False) + "\n"
        )
        state.doc_count += 1
        if state.doc_count % state.shard_size == 0:
            handle.close()
            state.shard_handle = None
            state.shard_index += 1

    batch.clear()


def _persist_encoding_metadata(
    *,
    state: _ShardState,
    vectors_dir: Path,
    source_path: Path,
    batch_size: int,
    provider: str,
) -> SpladeEncodingSummary:
    """Write metadata for an encoding run and return the summary.

    Returns
    -------
    SpladeEncodingSummary
        Summary describing the encoded corpus.
    """
    metadata = SpladeEncodingMetadata(
        doc_count=state.doc_count,
        shard_count=state.shard_count,
        quantization=state.quantization,
        batch_size=batch_size,
        provider=provider,
        vectors_dir=str(vectors_dir),
        source_path=str(source_path),
        prepared_at=datetime.now(UTC).isoformat(),
        generator=GENERATOR_NAME,
    )
    metadata_path = vectors_dir / ENCODING_METADATA_FILENAME
    _write_struct(metadata_path, metadata)
    return SpladeEncodingSummary(
        doc_count=state.doc_count,
        vectors_dir=str(vectors_dir),
        metadata_path=str(metadata_path),
        shard_count=state.shard_count,
    )


def _encode_records(
    *,
    encoder: _SparseEncoderProtocol,
    state: _ShardState,
    batch: list[tuple[str, str]],
    batch_size: int,
    source_path: Path,
) -> None:
    """Stream records from disk, validate them, and flush in batches.

    Raises
    ------
    TypeError
        If corpus entries are missing identifiers or text fields.
    """
    for record in _iter_corpus(source_path):
        doc_id = record.get("id")
        contents = record.get("contents") or record.get("text")
        if not isinstance(doc_id, str):
            msg = "SPLADE corpus entries must include string 'id' fields"
            raise TypeError(msg)
        if not isinstance(contents, str):
            msg = f"Document '{doc_id}' is missing textual contents"
            raise TypeError(msg)
        batch.append((doc_id, contents))
        if len(batch) >= batch_size:
            _flush_batch(encoder, batch, state)

    _flush_batch(encoder, batch, state)


def _optimize_export(
    encoder: _SparseEncoderProtocol,
    ctx: _ExportContext,
) -> Path:
    """Run graph optimization if requested and return the base ONNX path.

    Returns
    -------
    Path
        Path to the base ONNX artifact (optimized or original).
    """
    base_onnx = ctx.onnx_dir / "model.onnx"
    if not ctx.options.optimize:
        return base_onnx

    optimizer, _quantizer = _require_export_helpers()
    optimized_path = ctx.onnx_dir / "model_O3.onnx"
    optimizer(
        model=encoder,
        optimization_config="O3",
        model_name_or_path=str(ctx.model_dir),
        push_to_hub=False,
        create_pr=False,
    )
    return optimized_path if optimized_path.exists() else base_onnx


def _quantize_export(
    *,
    encoder: _SparseEncoderProtocol,
    ctx: _ExportContext,
    base_onnx: Path,
) -> bool:
    """Apply dynamic quantization and ensure the target ONNX exists.

    Returns
    -------
    bool
        ``True`` if a quantized artifact was produced; otherwise ``False``.
    """
    target_path = ctx.target_path
    options = ctx.options
    if not options.quantize:
        if base_onnx.exists() and not target_path.exists():
            shutil.copy2(base_onnx, target_path)
        return False

    _optimizer, quantizer = _require_export_helpers()
    quantizer(
        model=encoder,
        quantization_config=options.quantization_config,
        model_name_or_path=str(ctx.model_dir),
        push_to_hub=False,
        create_pr=False,
    )

    if target_path.exists():
        return True
    if base_onnx.exists():
        shutil.copy2(base_onnx, target_path)
        return True
    return False


def _persist_export_metadata(
    *,
    ctx: _ExportContext,
    quantized: bool,
) -> SpladeExportSummary:
    """Write export metadata and return the resulting summary.

    Returns
    -------
    SpladeExportSummary
        Summary describing the exported ONNX artifact.
    """
    metadata = SpladeArtifactMetadata(
        model_id=ctx.model_id,
        model_dir=str(ctx.model_dir),
        onnx_dir=str(ctx.onnx_dir),
        onnx_file=ctx.target_path.name,
        provider=ctx.provider,
        optimized=ctx.options.optimize,
        quantized=quantized,
        quantization_config=(ctx.options.quantization_config if ctx.options.quantize else None),
        exported_at=datetime.now(UTC).isoformat(),
        generator=GENERATOR_NAME,
    )
    metadata_path = ctx.onnx_dir / ARTIFACT_METADATA_FILENAME
    _write_struct(metadata_path, metadata)
    return SpladeExportSummary(onnx_file=str(ctx.target_path), metadata_path=str(metadata_path))


class SpladeArtifactsManager:
    """Manage SPLADE model exports and ONNX artifacts."""

    def __init__(self, settings: Settings, *, logger_: logging.Logger | None = None) -> None:
        self._settings = settings
        self._logger = logger_ or logging.getLogger(__name__)
        self._repo_root = Path(settings.paths.repo_root).expanduser().resolve()
        self._config = settings.splade

    @property
    def model_dir(self) -> Path:
        """Return the repository-relative directory containing saved SPLADE weights.

        Returns
        -------
        Path
            Absolute path to the configured SPLADE model directory.
        """
        return resolve_within_repo(self._repo_root, self._config.model_dir)

    @property
    def onnx_dir(self) -> Path:
        """Return the directory where exported ONNX artifacts are stored.

        Returns
        -------
        Path
            Absolute path to the configured ONNX artifacts directory.
        """
        return resolve_within_repo(self._repo_root, self._config.onnx_dir)

    def export_onnx(self, options: SpladeExportOptions | None = None) -> SpladeExportSummary:
        """Export SPLADE ONNX artifacts and record metadata.

        Parameters
        ----------
        options : SpladeExportOptions | None, optional
            Overrides for model identifier, provider, and export behaviour.

        Returns
        -------
        SpladeExportSummary
            Summary describing the exported artifact and metadata path.
        """
        opts = options or SpladeExportOptions()
        sparse_encoder_cls = _require_sparse_encoder()
        model_id = opts.model_id or self._config.model_id
        provider = opts.provider or self._config.provider
        model_dir = self.model_dir
        onnx_dir = self.onnx_dir
        onnx_dir.mkdir(parents=True, exist_ok=True)

        self._logger.info(
            "Exporting SPLADE model",
            extra={"model_id": model_id, "model_dir": str(model_dir), "provider": provider},
        )

        encoder = sparse_encoder_cls(model_id, backend="onnx", model_kwargs={"provider": provider})
        encoder.save_pretrained(str(model_dir))
        ctx = _ExportContext(
            model_id=model_id,
            model_dir=model_dir,
            onnx_dir=onnx_dir,
            provider=provider,
            target_path=onnx_dir / (opts.file_name or self._config.onnx_file),
            options=opts,
        )
        base_onnx = _optimize_export(encoder, ctx)
        quantized = _quantize_export(encoder=encoder, ctx=ctx, base_onnx=base_onnx)

        summary = _persist_export_metadata(ctx=ctx, quantized=quantized)
        self._logger.info(
            "Exported SPLADE artifacts",
            extra={"onnx_file": summary.onnx_file, "metadata": summary.metadata_path},
        )
        return summary


class SpladeEncoderService:
    """Encode corpora into SPLADE JsonVectorCollection shards."""

    def __init__(self, settings: Settings, *, logger_: logging.Logger | None = None) -> None:
        self._settings = settings
        self._logger = logger_ or logging.getLogger(__name__)
        self._repo_root = Path(settings.paths.repo_root).expanduser().resolve()
        self._config = settings.splade

    @property
    def vectors_dir(self) -> Path:
        """Return the directory that stores SPLADE JsonVectorCollection shards.

        Returns
        -------
        Path
            Absolute path to the configured vectors directory.
        """
        return resolve_within_repo(self._repo_root, self._config.vectors_dir)

    def _resolve_vectors_dir(self, override: str | Path | None) -> Path:
        """Resolve the vectors directory override or fall back to the configured path.

        Returns
        -------
        Path
            Absolute path to the directory where encoded vectors will be written.
        """
        if override is None:
            resolved = self.vectors_dir
        else:
            resolved = resolve_within_repo(self._repo_root, override)
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    def _build_encoder(self, *, provider: str, onnx_file: str | None) -> _SparseEncoderProtocol:
        """Instantiate a Sentence-Transformers SparseEncoder using configured paths.

        Returns
        -------
        _SparseEncoderProtocol
            Encoder instance configured for the requested provider and ONNX artifact.
        """
        sparse_encoder_cls = _require_sparse_encoder()
        model_dir = resolve_within_repo(self._repo_root, self._config.model_dir)
        onnx_dir = resolve_within_repo(self._repo_root, self._config.onnx_dir)
        candidate = onnx_dir / (onnx_file or self._config.onnx_file)
        if not candidate.exists():
            candidate = onnx_dir / self._config.onnx_file

        model_kwargs: dict[str, str] = {"provider": provider}
        if candidate.exists():
            model_kwargs["file_name"] = _serialize_relative(candidate, model_dir)

        return sparse_encoder_cls(
            str(model_dir),
            backend="onnx",
            model_kwargs=model_kwargs,
        )

    def encode_corpus(
        self,
        source: str | Path,
        options: SpladeEncodeOptions | None = None,
    ) -> SpladeEncodingSummary:
        """Encode ``source`` JSONL into SPLADE JsonVectorCollection shards.

        Parameters
        ----------
        source : str | Path
            Path to the JSONL corpus containing ``id`` and ``contents``/``text`` fields.
        options : SpladeEncodeOptions | None, optional
            Overrides for output directory, batch size, quantization, provider, and ONNX file.

        Returns
        -------
        SpladeEncodingSummary
            Summary including document count, vectors directory, metadata path, and shard count.

        Raises
        ------
        TypeError
            If corpus entries are missing identifiers or textual content.
        """
        opts = options or SpladeEncodeOptions()

        source_path = resolve_within_repo(self._repo_root, source, allow_nonexistent=False)
        vectors_dir = self._resolve_vectors_dir(opts.output_dir)
        batch_size = opts.batch_size or self._config.batch_size
        provider = opts.provider or self._config.provider

        encoder = self._build_encoder(provider=provider, onnx_file=opts.onnx_file)

        state = _ShardState(
            vectors_dir=vectors_dir,
            quantization=opts.quantization or self._config.quantization,
            shard_size=opts.shard_size,
        )
        batch: list[tuple[str, str]] = []

        try:
            _encode_records(
                encoder=encoder,
                state=state,
                batch=batch,
                batch_size=batch_size,
                source_path=source_path,
            )
        except TypeError as exc:
            raise TypeError(str(exc)) from exc

        if state.shard_handle is not None:
            state.shard_handle.close()
            state.shard_handle = None

        summary = _persist_encoding_metadata(
            state=state,
            vectors_dir=vectors_dir,
            source_path=source_path,
            batch_size=batch_size,
            provider=provider,
        )

        self._logger.info(
            "Encoded SPLADE corpus",
            extra={
                "doc_count": summary.doc_count,
                "vectors_dir": summary.vectors_dir,
                "metadata": summary.metadata_path,
            },
        )
        return summary


class SpladeIndexManager:
    """Build SPLADE Lucene impact indexes from vector collections."""

    def __init__(self, settings: Settings, *, logger_: logging.Logger | None = None) -> None:
        self._settings = settings
        self._logger = logger_ or logging.getLogger(__name__)
        self._repo_root = Path(settings.paths.repo_root).expanduser().resolve()
        self._config = settings.splade

    @property
    def vectors_dir(self) -> Path:
        """Return the configured JsonVectorCollection directory.

        Returns
        -------
        Path
            Absolute path to the JsonVectorCollection directory used for indexing.
        """
        return resolve_within_repo(self._repo_root, self._config.vectors_dir)

    @property
    def index_dir(self) -> Path:
        """Return the configured Lucene impact index directory.

        Returns
        -------
        Path
            Absolute path to the Lucene impact index output directory.
        """
        return resolve_within_repo(self._repo_root, self._config.index_dir)

    def build_index(self, options: SpladeBuildOptions | None = None) -> SpladeIndexMetadata:
        """Invoke Pyserini to build a SPLADE Lucene impact index.

        Parameters
        ----------
        options : SpladeBuildOptions | None, optional
            Overrides for vectors/index directories, thread count, clause limit, and overwrite.

        Returns
        -------
        SpladeIndexMetadata
            Metadata describing the resulting Lucene impact index.

        Raises
        ------
        FileExistsError
            If the index directory already exists and ``overwrite`` is ``False``.
        """
        options = options or SpladeBuildOptions()
        vectors_dir = (
            resolve_within_repo(self._repo_root, options.vectors_dir)
            if options.vectors_dir is not None
            else self.vectors_dir
        )
        index_dir = (
            resolve_within_repo(self._repo_root, options.index_dir)
            if options.index_dir is not None
            else self.index_dir
        )
        index_dir.parent.mkdir(parents=True, exist_ok=True)
        threads = options.threads or self._config.threads
        max_clause = options.max_clause_count or self._config.max_clause_count

        if index_dir.exists() and options.overwrite:
            shutil.rmtree(index_dir)
        elif index_dir.exists():
            msg = f"Index directory {index_dir} already exists and overwrite is disabled."
            raise FileExistsError(msg)

        env_overrides = os.environ.copy()
        env_overrides.setdefault(
            "JAVA_TOOL_OPTIONS",
            f"-Dorg.apache.lucene.maxClauseCount={max_clause}",
        )

        cmd = [
            os.fspath(Path(sys.executable)),
            "-m",
            "pyserini.index.lucene",
            "--collection",
            "JsonVectorCollection",
            "--input",
            str(vectors_dir),
            "--index",
            str(index_dir),
            "--generator",
            "DefaultLuceneDocumentGenerator",
            "--threads",
            str(threads),
            "--impact",
            "--pretokenized",
            "--optimize",
        ]

        self._logger.info(
            "Building SPLADE impact index",
            extra={
                "vectors_dir": str(vectors_dir),
                "index_dir": str(index_dir),
                "threads": threads,
                "max_clause_count": max_clause,
            },
        )
        run_subprocess(cmd, env=env_overrides)

        metadata_path = vectors_dir / ENCODING_METADATA_FILENAME
        corpus_digest = None
        doc_count: int | None = None
        if metadata_path.exists():
            metadata = msgspec.json.decode(metadata_path.read_bytes(), type=SpladeEncodingMetadata)
            doc_count = metadata.doc_count
            corpus_digest = metadata.source_path
        pyserini_version = _detect_pyserini_version()
        index_metadata = SpladeIndexMetadata(
            doc_count=doc_count,
            built_at=datetime.now(UTC).isoformat(),
            vectors_dir=str(vectors_dir),
            corpus_digest=corpus_digest,
            pyserini_version=pyserini_version,
            threads=threads,
            index_dir=str(index_dir),
            index_size_bytes=_directory_size(index_dir),
            generator=GENERATOR_NAME,
        )
        metadata_output = index_dir / INDEX_METADATA_FILENAME
        _write_struct(metadata_output, index_metadata)
        self._logger.info(
            "Built SPLADE impact index",
            extra={
                "index_dir": str(index_dir),
                "metadata": str(metadata_output),
                "doc_count": doc_count,
            },
        )
        return index_metadata


__all__ = [
    "SpladeArtifactMetadata",
    "SpladeArtifactsManager",
    "SpladeBuildOptions",
    "SpladeEncodeOptions",
    "SpladeEncodingMetadata",
    "SpladeEncodingSummary",
    "SpladeExportOptions",
    "SpladeExportSummary",
    "SpladeIndexManager",
    "SpladeIndexMetadata",
]
