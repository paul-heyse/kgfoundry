"""SPLADE artifact management, encoding, and Lucene impact index builders."""

from __future__ import annotations

import importlib
import json
import logging
import os
import shutil
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import msgspec

from codeintel_rev.io.path_utils import resolve_within_repo
from kgfoundry_common.subprocess_utils import run_subprocess

if TYPE_CHECKING:
    from codeintel_rev.config.settings import Settings

try:  # pragma: no cover - optional dependency
    from sentence_transformers import SparseEncoder
except Exception:  # pragma: no cover - handled at runtime
    SparseEncoder = None  # type: ignore[misc]

try:  # pragma: no cover - optional dependency
    from sentence_transformers import (
        export_dynamic_quantized_onnx_model,
        export_optimized_onnx_model,
    )
except Exception:  # pragma: no cover - handled at runtime
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


def _require_sparse_encoder() -> type:
    if SparseEncoder is None:  # pragma: no cover - defensive
        msg = (
            "sentence-transformers with SparseEncoder support is required for SPLADE "
            "operations. Install the 'sentence-transformers[onnx]' extra."
        )
        raise RuntimeError(msg)
    return SparseEncoder  # type: ignore[return-value]


def _require_export_helpers() -> tuple[object, object]:
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
        quantized = int(round(weight * quantization))
        if quantized > 0:
            vector[token] = quantized
    return vector


def _iter_corpus(path: Path) -> Iterable[dict[str, object]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


class SpladeArtifactsManager:
    """Manage SPLADE model exports and ONNX artifacts."""

    def __init__(self, settings: Settings, *, logger_: logging.Logger | None = None) -> None:
        self._settings = settings
        self._logger = logger_ or logging.getLogger(__name__)
        self._repo_root = Path(settings.paths.repo_root).expanduser().resolve()
        self._config = settings.splade

    @property
    def model_dir(self) -> Path:
        return resolve_within_repo(self._repo_root, self._config.model_dir)

    @property
    def onnx_dir(self) -> Path:
        return resolve_within_repo(self._repo_root, self._config.onnx_dir)

    def export_onnx(
        self,
        *,
        optimize: bool = True,
        quantize: bool = True,
        quantization_config: str = "avx2",
        provider: str | None = None,
        model_id: str | None = None,
        file_name: str | None = None,
    ) -> SpladeExportSummary:
        """Export SPLADE ONNX artifacts and record metadata.

        Parameters
        ----------
        optimize : bool, optional
            Whether to run Sentence-Transformers' graph optimizer (``O3``) after export.
        quantize : bool, optional
            When ``True`` run dynamic quantization to produce an int8 ONNX variant.
        quantization_config : str, optional
            Quantization preset passed to Sentence-Transformers (e.g., ``avx2`` or ``arm64``).
        provider : str | None, optional
            ONNX Runtime execution provider used during export. Defaults to configured provider.
        model_id : str | None, optional
            Hugging Face model identifier. Defaults to the configured SPLADE model id.
        file_name : str | None, optional
            Override for the exported ONNX file name. Defaults to ``SPLADE_ONNX_FILE``.

        Returns
        -------
        SpladeExportSummary
            Summary describing the exported artifact and metadata path.

        Raises
        ------
        RuntimeError
            If the required Sentence-Transformers components are unavailable.
        """
        sparse_encoder_cls = _require_sparse_encoder()
        model_id = model_id or self._config.model_id
        provider = provider or self._config.provider
        model_dir = self.model_dir
        onnx_dir = self.onnx_dir
        onnx_dir.mkdir(parents=True, exist_ok=True)

        self._logger.info(
            "Exporting SPLADE model",
            extra={"model_id": model_id, "model_dir": str(model_dir), "provider": provider},
        )

        encoder = sparse_encoder_cls(model_id, backend="onnx", model_kwargs={"provider": provider})
        encoder.save_pretrained(str(model_dir))

        base_onnx = onnx_dir / "model.onnx"
        if optimize:
            optimized_path = onnx_dir / "model_O3.onnx"
            optimizer, quantizer = _require_export_helpers()
            optimizer(
                model=encoder,
                optimization_config="O3",
                model_name_or_path=str(model_dir),
                push_to_hub=False,
                create_pr=False,
            )
            if optimized_path.exists():
                base_onnx = optimized_path

        target_file = file_name or self._config.onnx_file
        target_path = onnx_dir / target_file

        quantized = False
        if quantize:
            _optimizer, quantizer = _require_export_helpers()
            quantizer(
                model=encoder,
                quantization_config=quantization_config,
                model_name_or_path=str(model_dir),
                push_to_hub=False,
                create_pr=False,
            )
            # Some ST versions place the quantized file in onnx_dir automatically.
            # If not present, copy base ONNX as a conservative fallback.
            if target_path.exists():
                quantized = True
            elif base_onnx.exists():
                shutil.copy2(base_onnx, target_path)
                quantized = True
        elif base_onnx.exists():
            shutil.copy2(base_onnx, target_path)

        metadata = SpladeArtifactMetadata(
            model_id=model_id,
            model_dir=str(model_dir),
            onnx_dir=str(onnx_dir),
            onnx_file=target_file,
            provider=provider,
            optimized=optimize,
            quantized=quantized,
            quantization_config=quantization_config if quantize else None,
            exported_at=datetime.now(UTC).isoformat(),
            generator=GENERATOR_NAME,
        )
        metadata_path = onnx_dir / ARTIFACT_METADATA_FILENAME
        _write_struct(metadata_path, metadata)
        self._logger.info(
            "Exported SPLADE artifacts",
            extra={"onnx_file": str(target_path), "metadata": str(metadata_path)},
        )
        return SpladeExportSummary(onnx_file=str(target_path), metadata_path=str(metadata_path))


class SpladeEncoderService:
    """Encode corpora into SPLADE JsonVectorCollection shards."""

    def __init__(self, settings: Settings, *, logger_: logging.Logger | None = None) -> None:
        self._settings = settings
        self._logger = logger_ or logging.getLogger(__name__)
        self._repo_root = Path(settings.paths.repo_root).expanduser().resolve()
        self._config = settings.splade

    @property
    def vectors_dir(self) -> Path:
        return resolve_within_repo(self._repo_root, self._config.vectors_dir)

    def encode_corpus(
        self,
        source: str | Path,
        *,
        output_dir: str | Path | None = None,
        batch_size: int | None = None,
        quantization: int | None = None,
        shard_size: int = 100_000,
        provider: str | None = None,
        onnx_file: str | None = None,
    ) -> SpladeEncodingSummary:
        """Encode ``source`` JSONL into SPLADE JsonVectorCollection shards.

        Parameters
        ----------
        source : str | Path
            Path to the JSONL corpus containing ``id`` and ``contents``/``text`` fields.
        output_dir : str | Path | None, optional
            Directory for emitted JsonVectorCollection shards. Defaults to configured directory.
        batch_size : int | None, optional
            Batch size used during encoding. Defaults to the configured SPLADE batch size.
        quantization : int | None, optional
            Integer scaling factor applied to decoded token weights. Defaults to configuration.
        shard_size : int, optional
            Maximum number of documents per shard file before rotating to the next shard.
        provider : str | None, optional
            ONNX Runtime execution provider used for inference. Defaults to configured provider.
        onnx_file : str | None, optional
            Specific ONNX file to load. Defaults to ``SPLADE_ONNX_FILE``.

        Returns
        -------
        SpladeEncodingSummary
            Summary including document count, vectors directory, metadata path, and shard count.

        Raises
        ------
        RuntimeError
            If Sentence-Transformers is unavailable.
        ValueError
            If corpus entries are missing ``id`` or textual content fields.
        FileNotFoundError
            If the input corpus path does not exist.
        """
        sparse_encoder_cls = _require_sparse_encoder()

        source_path = resolve_within_repo(self._repo_root, source, allow_nonexistent=False)
        vectors_dir = (
            resolve_within_repo(self._repo_root, output_dir)
            if output_dir is not None
            else self.vectors_dir
        )
        vectors_dir.mkdir(parents=True, exist_ok=True)

        batch_size = batch_size or self._config.batch_size
        quantization = quantization or self._config.quantization
        provider = provider or self._config.provider

        model_dir = resolve_within_repo(self._repo_root, self._config.model_dir)
        onnx_dir = resolve_within_repo(self._repo_root, self._config.onnx_dir)
        resolved_onnx = onnx_dir / (onnx_file or self._config.onnx_file)
        if not resolved_onnx.exists():
            resolved_onnx = onnx_dir / self._config.onnx_file

        model_kwargs = {"provider": provider}
        if resolved_onnx.exists():
            relative = _serialize_relative(resolved_onnx, model_dir)
            model_kwargs["file_name"] = relative

        self._logger.info(
            "Encoding SPLADE corpus",
            extra={
                "source": str(source_path),
                "vectors_dir": str(vectors_dir),
                "batch_size": batch_size,
                "quantization": quantization,
                "provider": provider,
            },
        )

        encoder = sparse_encoder_cls(
            str(model_dir),
            backend="onnx",
            model_kwargs=model_kwargs,
        )

        doc_count = 0
        shard_index = 0
        shard_path: Path | None = None
        shard_handle = None

        def _open_writer(idx: int):
            path = vectors_dir / f"part-{idx:05d}.jsonl"
            return path, path.open("w", encoding="utf-8")

        batch_ids: list[str] = []
        batch_texts: list[str] = []
        shard_count = 0

        def _flush(current_ids: Sequence[str], current_texts: Sequence[str]) -> None:
            nonlocal shard_index, shard_handle, shard_path, doc_count, shard_count
            if not current_ids:
                return
            embeddings = encoder.encode_document(list(current_texts))
            decoded = encoder.decode(embeddings, top_k=None)
            for doc_id, token_pairs in zip(current_ids, decoded):
                vector = _quantize_tokens(token_pairs, quantization)
                if shard_handle is None:
                    shard_path, shard_handle = _open_writer(shard_index)
                    shard_count += 1
                assert shard_handle is not None  # for type checker
                shard_handle.write(
                    json.dumps(
                        {"id": doc_id, "contents": "", "vector": vector},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                doc_count += 1
                if doc_count % shard_size == 0:
                    shard_handle.close()
                    shard_handle = None
                    shard_index += 1

        for record in _iter_corpus(source_path):
            doc_id = record.get("id")
            contents = record.get("contents") or record.get("text")
            if not isinstance(doc_id, str):
                msg = "SPLADE corpus entries must include string 'id' fields"
                raise ValueError(msg)
            if not isinstance(contents, str):
                msg = f"Document '{doc_id}' is missing textual contents"
                raise ValueError(msg)
            batch_ids.append(doc_id)
            batch_texts.append(contents)
            if len(batch_ids) >= batch_size:
                _flush(batch_ids, batch_texts)
                batch_ids.clear()
                batch_texts.clear()

        _flush(batch_ids, batch_texts)

        if shard_handle is not None:
            shard_handle.close()

        metadata = SpladeEncodingMetadata(
            doc_count=doc_count,
            shard_count=shard_count,
            quantization=quantization,
            batch_size=batch_size,
            provider=provider,
            vectors_dir=str(vectors_dir),
            source_path=str(source_path),
            prepared_at=datetime.now(UTC).isoformat(),
            generator=GENERATOR_NAME,
        )
        metadata_path = vectors_dir / ENCODING_METADATA_FILENAME
        _write_struct(metadata_path, metadata)

        self._logger.info(
            "Encoded SPLADE corpus",
            extra={
                "doc_count": doc_count,
                "vectors_dir": str(vectors_dir),
                "metadata": str(metadata_path),
            },
        )
        return SpladeEncodingSummary(
            doc_count=doc_count,
            vectors_dir=str(vectors_dir),
            metadata_path=str(metadata_path),
            shard_count=shard_count,
        )


class SpladeIndexManager:
    """Build SPLADE Lucene impact indexes from vector collections."""

    def __init__(self, settings: Settings, *, logger_: logging.Logger | None = None) -> None:
        self._settings = settings
        self._logger = logger_ or logging.getLogger(__name__)
        self._repo_root = Path(settings.paths.repo_root).expanduser().resolve()
        self._config = settings.splade

    @property
    def vectors_dir(self) -> Path:
        return resolve_within_repo(self._repo_root, self._config.vectors_dir)

    @property
    def index_dir(self) -> Path:
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
        RuntimeError
            If Sentence-Transformers components required for metadata lookup are unavailable.
        SubprocessError
            When the underlying Pyserini command fails.
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
            os.fspath(Path(os.sys.executable)),
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
    "SpladeEncodingMetadata",
    "SpladeEncodingSummary",
    "SpladeExportSummary",
    "SpladeIndexManager",
    "SpladeIndexMetadata",
]
