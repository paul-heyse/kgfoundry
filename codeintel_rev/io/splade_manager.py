"""SPLADE artifact management, encoding, and Lucene impact index builders."""

from __future__ import annotations

import importlib
import json
import logging
import math
import os
import shutil
import statistics
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Protocol, TextIO, TypedDict, Unpack, cast

import msgspec
import numpy as np

from codeintel_rev._lazy_imports import LazyModule
from codeintel_rev.config.api import AppConfig, SpladeSettings
from codeintel_rev.io.path_utils import resolve_within_repo
from codeintel_rev.io.splade_engine import SPLADEEngine
from codeintel_rev.typing import NDArrayF32
from kgfoundry_common.subprocess_utils import run_subprocess


class _ImpactHit(Protocol):
    """Protocol describing SPLADE search hits."""

    docid: str | int
    score: float


class _EncoderProtocol(Protocol):
    """Protocol describing the encoder exposed by the searcher."""

    def encode(self, text: str) -> Sequence[float] | NDArrayF32:
        """Encode text into sparse vector representation."""
        ...


class _LuceneImpactSearcherProtocol(Protocol):
    """Protocol describing the Pyserini Lucene impact searcher surface we use."""

    encoder: _EncoderProtocol | None

    def search(self, query: str, k: int) -> Sequence[_ImpactHit]:
        """Return top-k SPLADE hits for the supplied query."""
        ...


if TYPE_CHECKING:

    class _SparseEncoderProtocol(Protocol):
        """Protocol defining the interface for SPLADE sparse encoders.

        This protocol describes the methods that SPLADE encoder implementations
        must provide for encoding documents and queries, decoding sparse vectors,
        and saving model artifacts. Used for type checking and dependency
        injection in SPLADE encoding operations.

        Methods
        -------
        encode_document(sentences: Sequence[str]) -> Sequence[object]
            Encode document texts into sparse vector embeddings.

        encode_query(queries: Sequence[str]) -> Sequence[object]
            Encode query texts into sparse vector embeddings.

        decode(embeddings: object, top_k: int | None = None) -> Sequence[Sequence[tuple[str, float]]]
            Decode sparse vector embeddings into token-weight pairs.

        save_pretrained(output_path: str) -> None
            Save the encoder model to disk for later loading.
        """

        def encode_document(self, sentences: Sequence[str]) -> Sequence[object]:
            """Encode document texts into sparse vector embeddings.

            Extended Summary
            ----------------
            This method processes a batch of document texts and produces sparse
            vector embeddings suitable for retrieval. The embeddings are typically
            high-dimensional sparse vectors where each dimension corresponds to a
            vocabulary token and the value represents the token's importance weight.
            The embeddings produced are optimized for document indexing and retrieval.

            Parameters
            ----------
            sentences : Sequence[str]
                Batch of document texts to encode. Each string represents one
                document from the corpus. The encoder processes the batch together
                for efficiency.

            Returns
            -------
            Sequence[object]
                Sparse vector embeddings for the input documents. The exact type
                depends on the encoder implementation (typically numpy arrays or
                PyTorch tensors). Each embedding represents one input document and
                can be decoded into token-weight pairs using decode(). This protocol
                method raises NotImplementedError and must be implemented by concrete
                classes.

            Raises
            ------
            NotImplementedError
                This is a protocol stub method that must be implemented by concrete classes.

            Notes
            -----
            The embeddings produced by this method are optimized for document
            indexing and retrieval. They typically have different characteristics
            than query embeddings (produced by encode_query()) to optimize for
            different use cases. Time complexity: O(batch_size * avg_doc_length)
            for encoding, plus model inference overhead.
            """
            _ = (self, sentences)
            raise NotImplementedError

        def encode_query(self, queries: Sequence[str]) -> Sequence[object]:
            """Encode query texts into sparse vector embeddings.

            Extended Summary
            ----------------
            This method processes a batch of query texts and produces sparse
            vector embeddings optimized for query-time retrieval. Query embeddings
            are designed to match against document embeddings produced by
            encode_document() for semantic search.

            Parameters
            ----------
            queries : Sequence[str]
                Batch of query texts to encode. Each string represents one search
                query. The encoder processes the batch together for efficiency.

            Returns
            -------
            Sequence[object]
                Sparse vector embeddings for the input queries. The exact type
                depends on the encoder implementation (typically numpy arrays or
                PyTorch tensors). Each embedding represents one input query and
                can be decoded into token-weight pairs using decode(). This protocol
                method raises NotImplementedError and must be implemented by concrete
                classes.

            Raises
            ------
            NotImplementedError
                This is a protocol stub method that must be implemented by concrete classes.

            Notes
            -----
            Query embeddings are optimized for retrieval against document embeddings.
            They may have different sparsity patterns or weight distributions than
            document embeddings to improve query-document matching. Time complexity:
            O(batch_size * avg_query_length) for encoding, plus model inference overhead.
            """
            _ = (self, queries)
            raise NotImplementedError

        def decode(
            self,
            embeddings: object,
            top_k: int | None = None,
        ) -> Sequence[Sequence[tuple[str, float]]]:
            """Decode sparse vector embeddings into token-weight pairs.

            Extended Summary
            ----------------
            This method converts sparse vector embeddings back into human-readable
            token-weight pairs. Each embedding is decoded into a sequence of
            (token, weight) tuples representing the most important tokens and their
            relevance scores. Optionally filters to top-k tokens by weight. The decode
            operation is typically used for inspecting which tokens contribute most to
            an embedding, converting embeddings to quantized token dictionaries for
            indexing, and debugging model behavior.

            Parameters
            ----------
            embeddings : object
                Sparse vector embeddings to decode. Typically numpy arrays or
                PyTorch tensors produced by encode_document() or encode_query().
                The embeddings should be in the format expected by the encoder
                implementation.
            top_k : int | None, optional
                Maximum number of top tokens to return per embedding. If None,
                returns all non-zero tokens. If specified, returns only the
                top-k tokens by weight (descending order). Defaults to None.

            Returns
            -------
            Sequence[Sequence[tuple[str, float]]]
                Decoded token-weight pairs for each input embedding. Outer sequence
                has one entry per input embedding. Inner sequence contains (token, weight)
                tuples sorted by weight (descending). Tokens are vocabulary strings;
                weights are floating-point relevance scores (typically non-negative,
                higher is more relevant). This protocol method raises NotImplementedError
                and must be implemented by concrete classes.

            Raises
            ------
            NotImplementedError
                This is a protocol stub method that must be implemented by concrete classes.

            Notes
            -----
            The decode operation is typically used for:
            - Inspecting which tokens contribute most to an embedding
            - Converting embeddings to quantized token dictionaries for indexing
            - Debugging and understanding model behavior
            Time complexity: O(n_embeddings * embedding_dim) for full decoding,
            O(n_embeddings * top_k * log(embedding_dim)) if top_k is specified.
            """
            _ = (self, embeddings, top_k)
            raise NotImplementedError

        def save_pretrained(self, output_path: str) -> None:
            """Save the encoder model to disk for later loading.

            This method persists the encoder's model weights, configuration, and
            vocabulary to disk so it can be loaded later without retraining. The
            saved model can be loaded by instantiating a new encoder with the
            same model identifier or path.

            Parameters
            ----------
            output_path : str
                Directory path where the model should be saved. The method creates
                this directory if it doesn't exist and writes model files (weights,
                config, vocabulary) into it. The path should be writable and have
                sufficient disk space for the model artifacts.

            Raises
            ------
            NotImplementedError
                This is a protocol stub method that must be implemented by concrete classes.

            Notes
            -----
            The saved model includes all components necessary for encoding:
            - Model weights (PyTorch state dict or ONNX format)
            - Tokenizer configuration and vocabulary
            - Model configuration (architecture, hyperparameters)
            The saved model can be loaded later using the same encoder class
            constructor with the output_path as the model identifier. Time
            complexity: O(model_size) for writing model files to disk. The method
            performs I/O operations and may take several seconds for large models.
            """
            _ = (self, output_path)
            raise NotImplementedError

    class _SparseEncoderFactory(Protocol):
        """Protocol for SparseEncoder factory function."""

        def __call__(
            self,
            model_id: str,
            *,
            backend: str,
            model_kwargs: Mapping[str, object] | None = None,
        ) -> _SparseEncoderProtocol: ...

    class _OptimizerKwargs(TypedDict):
        """Keyword arguments for SPLADE optimizer function.

        Attributes
        ----------
        optimization_config : str
            Optimization configuration string.
        model_name_or_path : str
            Model name or path identifier.
        push_to_hub : bool
            Whether to push optimized model to HuggingFace Hub.
        create_pr : bool
            Whether to create a pull request when pushing to hub.
        """

        optimization_config: str
        model_name_or_path: str
        push_to_hub: bool
        create_pr: bool

    class _OptimizerFunction(Protocol):
        """Protocol for SPLADE model optimization function."""

        def __call__(
            self,
            model: _SparseEncoderProtocol,
            **kwargs: Unpack[_OptimizerKwargs],
        ) -> None: ...

    class _QuantizerKwargs(TypedDict):
        """Keyword arguments for SPLADE quantizer function.

        Attributes
        ----------
        quantization_config : str | None
            Quantization configuration string, or None to skip quantization.
        model_name_or_path : str
            Model name or path identifier.
        push_to_hub : bool
            Whether to push quantized model to HuggingFace Hub.
        create_pr : bool
            Whether to create a pull request when pushing to hub.
        """

        quantization_config: str | None
        model_name_or_path: str
        push_to_hub: bool
        create_pr: bool

    class _QuantizerFunction(Protocol):
        """Protocol for SPLADE model quantization function."""

        def __call__(
            self,
            model: _SparseEncoderProtocol,
            **kwargs: Unpack[_QuantizerKwargs],
        ) -> None: ...


try:  # pragma: no cover - optional dependency
    from sentence_transformers import SparseEncoder as _SparseEncoderClass
except ImportError:  # pragma: no cover - handled at runtime
    _SparseEncoderClass = None

try:  # pragma: no cover - optional dependency
    from sentence_transformers import (
        export_dynamic_quantized_onnx_model as _export_dynamic_quantized_onnx_model,
    )
    from sentence_transformers import (
        export_optimized_onnx_model as _export_optimized_onnx_model,
    )
except ImportError:  # pragma: no cover - handled at runtime
    _export_dynamic_quantized_onnx_model = None
    _export_optimized_onnx_model = None


_lucene_search = LazyModule("pyserini.search.lucene", "splade impact runtime")


@dataclass(frozen=True, slots=True)
class SpladeQueryOptions:
    """Runtime knobs for SPLADE impact search.

    Attributes
    ----------
    top_k : int, optional
        Maximum number of results to return from SPLADE search. Must be
        positive. Defaults to 50.
    """

    top_k: int = 50


@dataclass(frozen=True, slots=True)
class SpladeHit:
    """Typed SPLADE hit row.

    Attributes
    ----------
    doc_id : int
        Document/chunk identifier returned by the search.
    score : float
        Relevance score for this hit. Higher scores indicate better matches.
    """

    doc_id: int
    score: float


class SpladeQueryEngine:
    """Thin Pyserini LuceneImpactSearcher wrapper."""

    def __init__(
        self,
        index_dir: Path,
        *,
        encoder: str | object | None = None,
        device: str | None = None,
    ) -> None:
        """Initialize SPLADE query engine.

        Parameters
        ----------
        index_dir : Path
            Path to the Lucene impact index directory.
        encoder : str | object | None, optional
            Pyserini encoder identifier or object to use for query encoding.
        device : str | None, optional
            Preferred device for the encoder, if applicable.
        """
        self._index_dir = Path(index_dir).resolve()
        self._encoder = encoder
        self._device = device
        self._searcher: _LuceneImpactSearcherProtocol | None = None

    def search(self, query: str, *, options: SpladeQueryOptions | None = None) -> list[SpladeHit]:
        """Execute SPLADE search and return typed hits.

        Parameters
        ----------
        query : str
            Query text to search for.
        options : SpladeQueryOptions | None, optional
            Optional SPLADE search configuration (top_k, etc.).

        Returns
        -------
        list[SpladeHit]
            List of SPLADE search hits sorted by score descending.
        """
        opts = options or SpladeQueryOptions()
        searcher = self._ensure_searcher()
        hits = searcher.search(query, k=int(opts.top_k))
        return [SpladeHit(doc_id=_docid_to_int(hit.docid), score=float(hit.score)) for hit in hits]

    def search_batch(
        self,
        queries: Sequence[str],
        *,
        options: SpladeQueryOptions | None = None,
    ) -> list[list[SpladeHit]]:
        """Execute SPLADE searches sequentially for ``queries``.

        Parameters
        ----------
        queries : Sequence[str]
            Sequence of query texts to search for.
        options : SpladeQueryOptions | None, optional
            Optional SPLADE search configuration applied to all queries.

        Returns
        -------
        list[list[SpladeHit]]
            Batched results mirroring the ``queries`` order.
        """
        return [self.search(query, options=options) for query in queries]

    def encode_query(self, text: str) -> NDArrayF32:
        """Return encoder output as a NumPy array when available.

        Parameters
        ----------
        text : str
            Query text to encode.

        Returns
        -------
        NDArrayF32
            Encoded SPLADE sparse vector representation.

        Raises
        ------
        NotImplementedError
            If the encoder does not support encoding.
        """
        searcher = self._ensure_searcher()
        encoder = getattr(searcher, "encoder", None)
        if encoder is None or not hasattr(encoder, "encode"):
            msg = "Underlying encoder does not expose encode()."
            raise NotImplementedError(msg)

        vector = encoder.encode(text)
        arr = np.asarray(vector, dtype=np.float32, order="C")
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        return cast("NDArrayF32", arr)

    def _ensure_searcher(self) -> _LuceneImpactSearcherProtocol:
        """Create or return a cached Lucene impact searcher instance.

        Returns
        -------
        _LuceneImpactSearcherProtocol
            A Pyserini LuceneImpactSearcher instance bound to the index directory
            and encoder. The searcher is cached after first creation and the encoder
            device is moved if specified.
        """
        searcher = self._searcher
        if searcher is not None:
            return searcher
        module = _lucene_search.module()
        searcher = cast(
            "_LuceneImpactSearcherProtocol",
            module.LuceneImpactSearcher(str(self._index_dir), self._encoder),
        )
        _maybe_move_encoder_device(searcher, self._device)
        self._searcher = searcher
        return searcher


def _docid_to_int(docid: str | int) -> int:
    """Convert a document ID to integer, handling various formats.

    Parameters
    ----------
    docid : str | int
        Document identifier. Can be an integer, a string integer, or a string
        with "chunk:" prefix. May also contain non-numeric suffixes.

    Returns
    -------
    int
        Integer representation of the document ID. Extracts numeric portion
        from strings with non-numeric suffixes. Returns -1 if no valid
        integer can be extracted.
    """
    text = str(docid).strip()
    if text.startswith("chunk:"):
        text = text.split(":", 1)[1]
    try:
        return int(text)
    except ValueError:
        digits = ""
        for char in reversed(text):
            if char.isdigit():
                digits = char + digits
            else:
                break
        try:
            return int(digits) if digits else -1
        except ValueError:
            return -1


def _maybe_move_encoder_device(searcher: _LuceneImpactSearcherProtocol, device: str | None) -> None:
    """Move encoder to specified device if supported.

    Parameters
    ----------
    searcher : object
        Pyserini searcher instance that may have an encoder attribute.
    device : str | None
        Target device name (e.g., "cuda", "cpu"). If None, no operation
        is performed.

    Notes
    -----
    This function attempts to move the encoder to the specified device by
    calling encoder.to(device). If the encoder doesn't support device
    movement or an error occurs, the operation is silently ignored.
    """
    if device is None:
        return
    encoder = getattr(searcher, "encoder", None)
    if encoder is None or not hasattr(encoder, "to"):
        return
    try:
        encoder.to(device)  # type: ignore[call-arg]
    except (AttributeError, RuntimeError, TypeError, ValueError):  # pragma: no cover - defensive
        return


GENERATOR_NAME = "codeintel_rev.io.splade_manager"
ARTIFACT_METADATA_FILENAME = "artifacts.json"
ENCODING_METADATA_FILENAME = "vectors_metadata.json"
INDEX_METADATA_FILENAME = "metadata.json"
_PERCENTILE_MIN = 0.0
_PERCENTILE_MAX = 100.0


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


class SpladeBenchmarkOptions(msgspec.Struct, frozen=True):
    """Options controlling SPLADE encoder latency benchmarks."""

    warmup_iterations: int = 3
    measure_iterations: int = 10
    provider: str | None = None
    onnx_file: str | None = None


class SpladeBenchmarkSummary(msgspec.Struct, frozen=True):
    """Summary describing SPLADE encoder latency benchmarks."""

    query_count: int
    warmup_iterations: int
    measure_iterations: int
    min_latency_ms: float
    max_latency_ms: float
    mean_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    provider: str
    onnx_file: str | None


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


@dataclass(frozen=True)
class _ShardState:
    """Mutable encoding state for shard rotation.

    Attributes
    ----------
    vectors_dir : Path
        Directory path where vector shard files are written.
    quantization : int
        Quantization level for model weights (typically 100 for int8).
    shard_size : int
        Maximum number of documents per shard. Must be positive.
    doc_count : int, optional
        Current number of documents written to the current shard. Defaults to 0.
    shard_index : int, optional
        Current shard index (0-based). Defaults to 0.
    shard_handle : TextIO | None, optional
        File handle for the current shard being written. None if no shard is
        currently open. Defaults to None.
    shard_count : int, optional
        Total number of shards created so far. Defaults to 0.
    """

    vectors_dir: Path
    quantization: int
    shard_size: int
    doc_count: int = 0
    shard_index: int = 0
    shard_handle: TextIO | None = None
    shard_count: int = 0


_SET_SHARD_STATE_ATTR = object.__setattr__


@dataclass(frozen=True)
class _ExportContext:
    """Context for SPLADE export operations.

    Attributes
    ----------
    model_id : str
        HuggingFace model identifier for the SPLADE model.
    model_dir : Path
        Directory path containing the SPLADE PyTorch model files.
    onnx_dir : Path
        Directory path where ONNX model files will be written.
    provider : str
        Device provider for ONNX execution (e.g., "CPUExecutionProvider").
    target_path : Path
        Target file path for the exported ONNX model.
    options : SpladeExportOptions
        Export options controlling optimization, quantization, and file naming.
    """

    model_id: str
    model_dir: Path
    onnx_dir: Path
    provider: str
    target_path: Path
    options: SpladeExportOptions


def _require_sparse_encoder() -> _SparseEncoderFactory:
    """Require SparseEncoder class to be available, raising if missing.

    Returns
    -------
    _SparseEncoderFactory
        SparseEncoder factory function.

    Raises
    ------
    RuntimeError
        If sentence-transformers doesn't provide SparseEncoder support.
    """
    if _SparseEncoderClass is None:  # pragma: no cover - defensive
        msg = (
            "sentence-transformers with SparseEncoder support is required for SPLADE "
            "operations. Install the 'sentence-transformers[onnx]' extra."
        )
        raise RuntimeError(msg)
    return cast("_SparseEncoderFactory", _SparseEncoderClass)


def _require_export_helpers() -> tuple[_OptimizerFunction, _QuantizerFunction]:
    """Require SPLADE export helper functions to be available, raising if missing.

    Returns
    -------
    tuple[_OptimizerFunction, _QuantizerFunction]
        Tuple of (optimizer function, quantizer function).

    Raises
    ------
    RuntimeError
        If sentence-transformers doesn't provide export helper functions.
    """
    if _export_optimized_onnx_model is None or _export_dynamic_quantized_onnx_model is None:
        msg = (
            "SPLADE export helpers are unavailable. Upgrade sentence-transformers to a "
            "version providing export_optimized_onnx_model and "
            "export_dynamic_quantized_onnx_model."
        )
        raise RuntimeError(msg)
    return cast("_OptimizerFunction", _export_optimized_onnx_model), cast(
        "_QuantizerFunction", _export_dynamic_quantized_onnx_model
    )


def _write_struct(target: Path, payload: msgspec.Struct) -> None:
    """Write msgspec struct to JSON file with UTF-8 encoding.

    Parameters
    ----------
    target : Path
        Target file path for JSON output.
    payload : msgspec.Struct
        Struct instance to serialize to JSON.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(msgspec.to_builtins(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _directory_size(path: Path) -> int:
    """Compute total size in bytes for all files beneath a directory.

    This utility function recursively traverses a directory tree and sums the
    sizes of all regular files found. It's used to calculate index sizes for
    metadata purposes. Symbolic links are followed, but directories themselves
    don't contribute to the size.

    Parameters
    ----------
    path : Path
        Root directory path to measure. The function recursively traverses all
        subdirectories and sums file sizes. The path must exist and be a directory.

    Returns
    -------
    int
        Total size in bytes for all regular files contained within the directory
        tree. Returns 0 if the directory is empty or contains no files. The
        size is calculated using file system stat information (st_size).
    """
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def _detect_pyserini_version() -> str:
    """Detect pyserini package version, returning "unknown" if unavailable.

    Returns
    -------
    str
        Version string from pyserini.__version__, or "unknown" if module missing.
    """
    try:
        module = importlib.import_module("pyserini")
    except ModuleNotFoundError:  # pragma: no cover - fallback
        return "unknown"
    version = getattr(module, "__version__", None)
    return str(version) if version is not None else "unknown"


@dataclass(frozen=True)
class SpladeEncoderContext:
    """Dependency provider for acquiring SPLADE encoder classes.

    Attributes
    ----------
    encoder_factory : Callable[[], _SparseEncoderFactory]
        Factory function that returns a SparseEncoder factory. Used for
        dependency injection in tests.
    """

    encoder_factory: Callable[[], _SparseEncoderFactory]

    @classmethod
    def production(cls) -> SpladeEncoderContext:
        """Return the encoder context used in production.

        Returns
        -------
        SpladeEncoderContext
            Context supplying the real sparse encoder factory.
        """
        return cls(encoder_factory=_require_sparse_encoder)


@dataclass(frozen=True)
class SpladeArtifactsContext:
    """Dependencies for artifact export operations.

    Attributes
    ----------
    encoder_context : SpladeEncoderContext
        Encoder context providing SPLADE encoder factory.
    export_helpers_factory : Callable[[], tuple[_OptimizerFunction, _QuantizerFunction]]
        Factory function that returns (optimizer, quantizer) helper functions
        for ONNX export. Used for dependency injection in tests.
    clock : Callable[[], datetime]
        Clock function returning current UTC datetime. Used for timestamping
        exported artifacts. Used for dependency injection in tests.
    """

    encoder_context: SpladeEncoderContext
    export_helpers_factory: Callable[[], tuple[_OptimizerFunction, _QuantizerFunction]]
    clock: Callable[[], datetime]

    @classmethod
    def production(cls) -> SpladeArtifactsContext:
        """Return the artifact context used in production.

        Returns
        -------
        SpladeArtifactsContext
            Context configured with encoder, helper, and clock factories.
        """
        return cls(
            encoder_context=SpladeEncoderContext.production(),
            export_helpers_factory=_require_export_helpers,
            clock=lambda: datetime.now(UTC),
        )


@dataclass(frozen=True)
class SpladeIndexContext:
    """Dependencies for SPLADE Lucene index builds.

    Attributes
    ----------
    subprocess_runner : Callable[[list[str], Mapping[str, str] | None], str]
        Function that runs subprocess commands and returns stdout. Used for
        dependency injection in tests.
    version_provider : Callable[[], str]
        Function that returns the pyserini version string. Used for dependency
        injection in tests.
    directory_size : Callable[[Path], int]
        Function that computes total size of all files in a directory. Used
        for dependency injection in tests.
    clock : Callable[[], datetime]
        Clock function returning current UTC datetime. Used for timestamping
        index builds. Used for dependency injection in tests.
    """

    subprocess_runner: Callable[[list[str], Mapping[str, str] | None], str]
    version_provider: Callable[[], str]
    directory_size: Callable[[Path], int]
    clock: Callable[[], datetime]

    @classmethod
    def production(cls) -> SpladeIndexContext:
        """Return the default index context.

        Returns
        -------
        SpladeIndexContext
            Context configured with production subprocess, clock, and version providers.
        """
        return cls(
            subprocess_runner=lambda cmd, env=None: run_subprocess(cmd, env=env),
            version_provider=_detect_pyserini_version,
            directory_size=_directory_size,
            clock=lambda: datetime.now(UTC),
        )


def _serialize_relative(path: Path, base: Path) -> str:
    """Serialize path relative to base, falling back to absolute string if not relative.

    Parameters
    ----------
    path : Path
        Path to serialize.
    base : Path
        Base path for relative calculation.

    Returns
    -------
    str
        Relative path string if path is relative to base, otherwise absolute path string.
    """
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _percentile_value(sorted_values: Sequence[float], percentile: float) -> float:
    """Return the percentile value using linear interpolation.

    Parameters
    ----------
    sorted_values : Sequence[float]
        Non-empty sorted sequence of latency values.
    percentile : float
        Desired percentile in the inclusive range [0, 100].

    Returns
    -------
    float
        Interpolated percentile value.

    Raises
    ------
    ValueError
        If :paramref:`sorted_values` is empty.
    """
    if not sorted_values:
        message = "sorted_values cannot be empty."
        raise ValueError(message)
    if len(sorted_values) == 1:
        return sorted_values[0]
    if percentile <= _PERCENTILE_MIN:
        return sorted_values[0]
    if percentile >= _PERCENTILE_MAX:
        return sorted_values[-1]

    rank = (percentile / _PERCENTILE_MAX) * (len(sorted_values) - 1)
    lower_index = math.floor(rank)
    upper_index = math.ceil(rank)
    if lower_index == upper_index:
        return sorted_values[lower_index]
    interpolation = rank - lower_index
    lower_value = sorted_values[lower_index]
    upper_value = sorted_values[upper_index]
    return lower_value + (upper_value - lower_value) * interpolation


def _quantize_tokens(pairs: Sequence[tuple[str, float]], quantization: int) -> dict[str, int]:
    """Quantize token weights to integer values using rounding.

    Parameters
    ----------
    pairs : Sequence[tuple[str, float]]
        Sequence of (token, weight) pairs to quantize.
    quantization : int
        Quantization factor (multiplier for weights).

    Returns
    -------
    dict[str, int]
        Dictionary mapping tokens to quantized integer weights (only positive weights included).
    """
    vector: dict[str, int] = {}
    for token, weight in pairs:
        if weight <= 0:
            continue
        quantized = math.floor(weight * float(quantization) + 0.5)
        if quantized > 0:
            vector[token] = quantized
    return vector


def _iter_corpus(path: Path) -> Iterable[dict[str, object]]:
    """Iterate over JSONL corpus file, yielding parsed JSON objects.

    Parameters
    ----------
    path : Path
        Path to JSONL corpus file.

    Yields
    ------
    dict[str, object]
        Parsed JSON object from each non-empty line.
    """
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            yield json.loads(line)


def _open_writer(vectors_dir: Path, index: int) -> tuple[Path, TextIO]:
    """Create a shard writer for the given shard index.

    This helper function creates a new JSONL shard file for writing encoded
    vectors. Shard files are named with zero-padded indices (e.g., part-00000.jsonl,
    part-00001.jsonl) to ensure proper ordering and easy identification. The file
    is opened in write mode with UTF-8 encoding.

    Parameters
    ----------
    vectors_dir : Path
        Directory where shard files are stored. The directory should already
        exist (created by the caller). Shard files are written directly to this
        directory.
    index : int
        Zero-based shard index. Used to generate the shard filename with zero
        padding (5 digits). Must be non-negative.

    Returns
    -------
    tuple[Path, TextIO]
        Tuple containing:
        - Path to the created shard file (e.g., vectors_dir/part-00000.jsonl)
        - Open text file handle in write mode, UTF-8 encoded, ready for writing
          JSONL records. The caller is responsible for closing the handle.
    """
    shard_path = vectors_dir / f"part-{index:05d}.jsonl"
    return shard_path, shard_path.open("w", encoding="utf-8")


def _flush_batch(
    encoder: _SparseEncoderProtocol,
    batch: list[tuple[str, str]],
    state: _ShardState,
) -> None:
    """Encode and persist the current batch of documents.

    This function processes a batch of documents by encoding them using the
    SPLADE encoder, decoding the sparse vectors into token-weight pairs, quantizing
    the weights, and writing the results to JSONL shard files. The batch is
    cleared after processing.

    The function handles shard file management automatically, creating new shard
    files when needed based on the configured shard size. Documents are written
    in JSONL format with document ID, empty contents (for compatibility), and
    the quantized sparse vector.

    Parameters
    ----------
    encoder : _SparseEncoderProtocol
        SPLADE encoder instance used to encode document texts into sparse vectors.
        The encoder must support encode_document() and decode() methods.
    batch : list[tuple[str, str]]
        List of (document_id, text) tuples to encode. Each tuple represents one
        document from the corpus. The batch is cleared after processing.
    state : _ShardState
        Mutable state object tracking shard file handles, document counts, shard
        indices, and encoding parameters. The state is updated as documents are
        written and shard files are rotated.

    Raises
    ------
    RuntimeError
        If a shard file handle unexpectedly becomes None during writing. This
        should not occur in normal operation and indicates a programming error
        or resource management issue.
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
            _SET_SHARD_STATE_ATTR(state, "shard_handle", handle)
            _SET_SHARD_STATE_ATTR(state, "shard_count", state.shard_count + 1)
        handle = state.shard_handle
        if handle is None:  # pragma: no cover - defensive
            msg = "Shard handle unexpectedly missing during encoding."
            raise RuntimeError(msg)
        handle.write(
            json.dumps({"id": doc_id, "contents": "", "vector": vector}, ensure_ascii=False) + "\n"
        )
        _SET_SHARD_STATE_ATTR(state, "doc_count", state.doc_count + 1)
        if state.doc_count % state.shard_size == 0:
            handle.close()
            _SET_SHARD_STATE_ATTR(state, "shard_handle", None)
            _SET_SHARD_STATE_ATTR(state, "shard_index", state.shard_index + 1)

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

    This function creates and persists metadata about a SPLADE encoding operation,
    including document counts, shard information, encoding parameters, and
    provenance data. The metadata is written as JSON to a standard location
    within the vectors directory and can be used later to verify corpus integrity
    and understand encoding configuration.

    Parameters
    ----------
    state : _ShardState
        Encoding state object containing accumulated statistics: document count,
        shard count, quantization parameter, and other encoding metadata. The
        state reflects the final state after all documents have been encoded.
    vectors_dir : Path
        Directory where encoded vector shards are stored. The metadata file will
        be written to this directory with a standard filename.
    source_path : Path
        Path to the original JSONL corpus file that was encoded. Stored in
        metadata for provenance tracking and corpus identification.
    batch_size : int
        Batch size used during encoding. This parameter affects encoding
        throughput and memory usage. Stored in metadata for reproducibility.
    provider : str
        ONNX runtime provider used for encoding (e.g., "cpu", "cuda", "tensorrt").
        Affects encoding performance and hardware requirements. Stored for
        reproducibility and performance analysis.

    Returns
    -------
    SpladeEncodingSummary
        Summary object containing:
        - doc_count: Total number of documents encoded
        - vectors_dir: Directory path where shards are stored
        - metadata_path: Path to the written metadata JSON file
        - shard_count: Number of shard files created
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

    This function orchestrates the encoding process by reading JSONL records from
    a corpus file, validating that each record has required fields (id and
    contents/text), accumulating records into batches, and flushing batches when
    they reach the configured size. The final batch is flushed even if it's
    smaller than the batch size.

    The function handles streaming large corpora efficiently by processing records
    one at a time and batching encoding operations. This minimizes memory usage
    while maintaining good throughput through batch encoding.

    Parameters
    ----------
    encoder : _SparseEncoderProtocol
        SPLADE encoder instance used to encode document texts. The encoder
        processes batches of texts and returns sparse vector representations.
    state : _ShardState
        Mutable encoding state tracking shard files, document counts, and encoding
        parameters. Updated as batches are flushed and documents are written.
    batch : list[tuple[str, str]]
        Accumulator list for batching documents. Documents are added to this list
        until it reaches batch_size, then the batch is flushed. The list is
        cleared after each flush. Must be empty initially.
    batch_size : int
        Maximum number of documents to accumulate before flushing. Larger batches
        improve encoding throughput but increase memory usage. Must be positive.
    source_path : Path
        Path to the JSONL corpus file to encode. The file is read line-by-line
        and each line is parsed as JSON. The file must exist and be readable.

    Raises
    ------
    TypeError
        Raised when corpus entries violate type requirements:
        - Document 'id' field is missing or not a string
        - Document is missing both 'contents' and 'text' fields, or the content
          field is not a string

    Notes
    -----
    Exception Propagation:
        This function may propagate exceptions from underlying operations:
        - FileNotFoundError: If the source_path does not exist (from file operations
          in _iter_corpus)
        - json.JSONDecodeError: If a line in the corpus file contains invalid JSON
          (from json.loads() in _iter_corpus)
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
    *,
    optimizer: _OptimizerFunction | None,
) -> Path:
    """Run graph optimization if requested and return the base ONNX path.

    This function conditionally applies ONNX graph optimizations to improve
    inference performance. If optimization is enabled in the export context,
    it runs the optimizer with O3 optimization level (aggressive optimizations)
    and returns the path to the optimized model. Otherwise, returns the path
    to the original unoptimized model.

    Graph optimization can significantly improve inference latency and reduce
    model size by applying transformations like constant folding, operator fusion,
    and dead code elimination. However, optimization may increase export time.

    Parameters
    ----------
    encoder : _SparseEncoderProtocol
        SPLADE encoder model to optimize. The encoder must support the optimization
        interface provided by sentence-transformers export helpers.
    ctx : _ExportContext
        Export context containing export options, directory paths, model
        identifier, and provider information. The ctx.options.optimize flag
        determines whether optimization is performed.
    optimizer : _OptimizerFunction | None
        Callable responsible for running optimization passes. When ``None``,
        optimization is skipped regardless of configuration.

    Returns
    -------
    Path
        Path to the ONNX model file to use as the base for further processing
        (quantization, etc.). If optimization was performed and successful,
        returns the optimized model path (model_O3.onnx). Otherwise, returns
        the original model path (model.onnx).
    """
    base_onnx = ctx.onnx_dir / "model.onnx"
    if not ctx.options.optimize or optimizer is None:
        return base_onnx

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
    quantizer: _QuantizerFunction | None,
) -> bool:
    """Apply dynamic quantization and ensure the target ONNX exists.

    This function conditionally applies dynamic quantization to the ONNX model
    to reduce model size and potentially improve inference speed. If quantization
    is enabled, it uses the configured quantization settings to produce a
    quantized model. If quantization is disabled or fails, it ensures the target
    path exists by copying the base model if needed.

    Dynamic quantization converts floating-point weights to lower precision
    (typically INT8) while maintaining model accuracy. This reduces model size
    and can improve inference speed on certain hardware, but may slightly
    degrade accuracy.

    Parameters
    ----------
    encoder : _SparseEncoderProtocol
        SPLADE encoder model to quantize. The encoder must support the quantization
        interface provided by sentence-transformers export helpers.
    ctx : _ExportContext
        Export context containing quantization options, target path, model
        directories, and provider information. The ctx.options.quantize flag
        determines whether quantization is performed, and ctx.options.quantization_config
        specifies quantization parameters.
    base_onnx : Path
        Path to the base ONNX model file (optimized or original). This is the
        input for quantization. If quantization is disabled, this file is copied
        to the target path.
    quantizer : _QuantizerFunction | None
        Callable that performs quantization. When ``None``, quantization is skipped.

    Returns
    -------
    bool
        True if a quantized artifact was successfully produced and exists at
        the target path. False if quantization was disabled, failed, or the
        base model was copied instead. Used by callers to determine which model
        file was actually created.
    """
    target_path = ctx.target_path
    options = ctx.options
    if not options.quantize:
        if base_onnx.exists() and not target_path.exists():
            shutil.copy2(base_onnx, target_path)
        return False

    if quantizer is None:
        return False
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
    exported_at: datetime | None = None,
) -> SpladeExportSummary:
    """Write export metadata and return the resulting summary.

    This function creates and persists metadata about a SPLADE ONNX export
    operation, including model identifier, export paths, provider information,
    optimization and quantization status, and export timestamp. The metadata
    is written as JSON to a standard location and can be used to verify exports
    and understand export configuration.

    Parameters
    ----------
    ctx : _ExportContext
        Export context containing all export information: model identifier,
        directory paths, provider, target file path, and export options
        (optimization, quantization settings). Used to populate metadata fields.
    quantized : bool
        Flag indicating whether the exported model is quantized. Determines
        which quantization configuration (if any) is stored in metadata. True
        if dynamic quantization was successfully applied, False otherwise.
    exported_at : datetime | None, optional
        Timestamp to record in metadata. When ``None`` the current UTC time is used.

    Returns
    -------
    SpladeExportSummary
        Summary object containing:
        - onnx_file: Path to the exported ONNX model file (relative or absolute)
        - metadata_path: Path to the written metadata JSON file
        The summary can be used to locate the exported artifacts and verify
        export completion.
    """
    timestamp = (exported_at or datetime.now(UTC)).isoformat()
    metadata = SpladeArtifactMetadata(
        model_id=ctx.model_id,
        model_dir=str(ctx.model_dir),
        onnx_dir=str(ctx.onnx_dir),
        onnx_file=ctx.target_path.name,
        provider=ctx.provider,
        optimized=ctx.options.optimize,
        quantized=quantized,
        quantization_config=(ctx.options.quantization_config if ctx.options.quantize else None),
        exported_at=timestamp,
        generator=GENERATOR_NAME,
    )
    metadata_path = ctx.onnx_dir / ARTIFACT_METADATA_FILENAME
    _write_struct(metadata_path, metadata)
    return SpladeExportSummary(onnx_file=str(ctx.target_path), metadata_path=str(metadata_path))


class SpladeArtifactsManager:
    """Manage SPLADE model exports and ONNX artifacts."""

    def __init__(
        self,
        app_config: AppConfig,
        *,
        logger_: logging.Logger | None = None,
        artifacts_context: SpladeArtifactsContext | None = None,
    ) -> None:
        """Initialize SPLADE artifacts manager.

        Parameters
        ----------
        app_config : AppConfig
            Application configuration containing SPLADE settings and paths.
        logger_ : logging.Logger | None, optional
            Custom logger instance. If None, uses module logger.
        artifacts_context : SpladeArtifactsContext | None, optional
            Context for artifact management. If None, uses production context.
        """
        self._logger = logger_ or logging.getLogger(__name__)
        self._repo_root = Path(app_config.paths.repo_root).expanduser().resolve()
        self._config: SpladeSettings = app_config.splade
        self._artifacts_context = artifacts_context or SpladeArtifactsContext.production()

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
        sparse_encoder_factory = self._artifacts_context.encoder_context.encoder_factory()
        optimizer, quantizer = self._artifacts_context.export_helpers_factory()
        model_id = opts.model_id or self._config.model_id
        provider = opts.provider or self._config.provider
        model_dir = self.model_dir
        onnx_dir = self.onnx_dir
        onnx_dir.mkdir(parents=True, exist_ok=True)

        self._logger.info(
            "Exporting SPLADE model",
            extra={
                "model_id": model_id,
                "model_dir": str(model_dir),
                "provider": provider,
            },
        )

        encoder = sparse_encoder_factory(
            model_id,
            backend="onnx",
            model_kwargs={"provider": provider},
        )
        encoder.save_pretrained(str(model_dir))
        ctx = _ExportContext(
            model_id=model_id,
            model_dir=model_dir,
            onnx_dir=onnx_dir,
            provider=provider,
            target_path=onnx_dir / (opts.file_name or self._config.onnx_file),
            options=opts,
        )
        base_onnx = _optimize_export(encoder, ctx, optimizer=optimizer)
        quantized = _quantize_export(
            encoder=encoder,
            ctx=ctx,
            base_onnx=base_onnx,
            quantizer=quantizer,
        )

        summary = _persist_export_metadata(
            ctx=ctx,
            quantized=quantized,
            exported_at=self._artifacts_context.clock(),
        )
        self._logger.info(
            "Exported SPLADE artifacts",
            extra={"onnx_file": summary.onnx_file, "metadata": summary.metadata_path},
        )
        return summary


class SpladeEncoderService:
    """Encode corpora into SPLADE JsonVectorCollection shards."""

    def __init__(
        self,
        app_config: AppConfig,
        *,
        logger_: logging.Logger | None = None,
        encoder_context: SpladeEncoderContext | None = None,
        timer: Callable[[], float] | None = None,
    ) -> None:
        """Initialize SPLADE encoder service.

        Parameters
        ----------
        app_config : AppConfig
            Application configuration containing SPLADE settings and paths.
        logger_ : logging.Logger | None, optional
            Custom logger instance. If None, uses module logger.
        encoder_context : SpladeEncoderContext | None, optional
            Encoder context for dependency injection. If None, uses production
            context.
        timer : Callable[[], float] | None, optional
            Timer function for performance measurement. If None, uses
            time.perf_counter.
        """
        self._logger = logger_ or logging.getLogger(__name__)
        self._encoder_context = encoder_context or SpladeEncoderContext.production()
        self._timer = timer or perf_counter
        self._repo_root = Path(app_config.paths.repo_root).expanduser().resolve()
        self._config: SpladeSettings = app_config.splade

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

        This method resolves the output directory for encoded vectors, either
        using an explicit override path or falling back to the configured default.
        The directory is created if it doesn't exist, ensuring it's ready for
        writing shard files.

        Parameters
        ----------
        override : str | Path | None, optional
            Optional override path for the vectors directory. If provided, this
            path is resolved relative to the repository root and used instead of
            the configured default. If None, uses the configured vectors_dir
            from settings. Defaults to None.

        Returns
        -------
        Path
            Absolute path to the directory where encoded vectors will be written.
            The directory is guaranteed to exist (created if necessary). The path
            is resolved relative to the repository root and normalized.
        """
        if override is None:
            resolved = self.vectors_dir
        else:
            resolved = resolve_within_repo(self._repo_root, override)
        resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    def _initialise_encoder(
        self,
        *,
        provider: str,
        onnx_file: str | None,
    ) -> tuple[_SparseEncoderProtocol, str | None]:
        """Instantiate a SparseEncoder and return the resolved ONNX artifact (if any).

        This method initializes a SPLADE sparse encoder instance, searching for
        ONNX model files in a priority order: explicit onnx_file parameter,
        configured default ONNX file, or falls back to PyTorch model if no ONNX
        file is found. The encoder is configured with the specified provider
        (CPU, CUDA, etc.) for inference.

        The method searches multiple candidate paths to find an available ONNX
        model, preferring explicitly specified files over defaults. If an ONNX
        file is found, it's used for faster inference. Otherwise, the encoder
        falls back to the PyTorch model.

        Parameters
        ----------
        provider : str
            ONNX runtime provider to use for inference (e.g., "cpu", "cuda",
            "tensorrt"). The provider determines which hardware/backend is used
            for model execution. Must be a valid provider name supported by the
            ONNX runtime.
        onnx_file : str | None, optional
            Optional explicit ONNX filename to use. If provided, this file is
            searched first in the ONNX directory. If not found or None, falls
            back to the configured default ONNX filename. Defaults to None.

        Returns
        -------
        tuple[_SparseEncoderProtocol, str | None]
            Tuple containing:
            - Encoder instance ready for encoding operations. The encoder is
              configured with the found ONNX model (if available) or PyTorch
              model, using the specified provider.
            - Relative path to the ONNX file used (relative to model_dir), or
              None if no ONNX file was found and PyTorch model was used instead.
              This path can be stored in metadata for reproducibility.
        """
        sparse_encoder_factory = self._encoder_context.encoder_factory()
        model_dir = resolve_within_repo(self._repo_root, self._config.model_dir)
        onnx_dir = resolve_within_repo(self._repo_root, self._config.onnx_dir)
        search_paths: list[Path] = []
        if onnx_file is not None:
            search_paths.append(onnx_dir / onnx_file)
        default_candidate = onnx_dir / self._config.onnx_file
        if default_candidate not in search_paths:
            search_paths.append(default_candidate)

        model_kwargs: dict[str, str] = {"provider": provider}
        selected_relative: str | None = None
        for candidate in search_paths:
            if candidate.exists():
                relative_path = _serialize_relative(candidate, model_dir)
                model_kwargs["file_name"] = relative_path
                selected_relative = relative_path
                break

        encoder_instance = sparse_encoder_factory(
            str(model_dir),
            backend="onnx",
            model_kwargs=model_kwargs,
        )
        return encoder_instance, selected_relative

    def _build_encoder(self, *, provider: str, onnx_file: str | None) -> _SparseEncoderProtocol:
        """Build sparse encoder instance from provider and optional ONNX file.

        Parameters
        ----------
        provider : str
            Encoder provider identifier.
        onnx_file : str | None
            Optional path to ONNX model file.

        Returns
        -------
        _SparseEncoderProtocol
            Initialized sparse encoder instance.
        """
        encoder, _ = self._initialise_encoder(provider=provider, onnx_file=onnx_file)
        return encoder

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
            _SET_SHARD_STATE_ATTR(state, "shard_handle", None)

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

    def benchmark_queries(
        self,
        queries: Sequence[str],
        options: SpladeBenchmarkOptions | None = None,
    ) -> SpladeBenchmarkSummary:
        """Benchmark SPLADE query encoding latency.

        Parameters
        ----------
        queries : Sequence[str]
            One or more query strings to encode during the benchmark.
        options : SpladeBenchmarkOptions | None, optional
            Benchmark configuration overrides. Defaults to :class:`SpladeBenchmarkOptions`.

        Returns
        -------
        SpladeBenchmarkSummary
            Latency statistics captured across the measured iterations.

        Raises
        ------
        ValueError
            Raised when the query list is empty or the benchmark configuration is invalid.
        """
        normalised = [
            query.strip() for query in queries if isinstance(query, str) and query.strip()
        ]
        if not normalised:
            msg = "At least one non-empty query must be provided for benchmarking."
            raise ValueError(msg)

        opts = options or SpladeBenchmarkOptions()
        if opts.warmup_iterations < 0:
            msg = "warmup_iterations must be zero or greater."
            raise ValueError(msg)
        if opts.measure_iterations < 1:
            msg = "measure_iterations must be at least one."
            raise ValueError(msg)

        provider = opts.provider or self._config.provider
        encoder, selected_relative = self._initialise_encoder(
            provider=provider,
            onnx_file=opts.onnx_file,
        )

        # Warm-up iterations prime the ONNX runtime for more stable latency measurements.
        for _ in range(opts.warmup_iterations):
            encoder.encode_query(list(normalised))

        latencies: list[float] = []
        for _ in range(opts.measure_iterations):
            start = self._timer()
            encoder.encode_query(list(normalised))
            elapsed = (self._timer() - start) * 1000.0
            latencies.append(elapsed)

        latencies.sort()
        summary = SpladeBenchmarkSummary(
            query_count=len(normalised),
            warmup_iterations=opts.warmup_iterations,
            measure_iterations=opts.measure_iterations,
            min_latency_ms=min(latencies),
            max_latency_ms=max(latencies),
            mean_latency_ms=statistics.fmean(latencies),
            p50_latency_ms=statistics.median(latencies),
            p95_latency_ms=_percentile_value(latencies, 95.0),
            p99_latency_ms=_percentile_value(latencies, 99.0),
            provider=provider,
            onnx_file=selected_relative,
        )

        self._logger.info(
            "Benchmarked SPLADE encoder",
            extra={
                "query_count": summary.query_count,
                "warmup_iterations": summary.warmup_iterations,
                "measure_iterations": summary.measure_iterations,
                "p50_ms": summary.p50_latency_ms,
                "p95_ms": summary.p95_latency_ms,
                "provider": summary.provider,
            },
        )

        return summary


class SpladeIndexManager:
    """Build SPLADE Lucene impact indexes from vector collections."""

    def __init__(
        self,
        app_config: AppConfig,
        *,
        logger_: logging.Logger | None = None,
        index_context: SpladeIndexContext | None = None,
    ) -> None:
        """Initialize SPLADE index manager.

        Parameters
        ----------
        app_config : AppConfig
            Application configuration containing SPLADE settings.
        logger_ : logging.Logger | None, optional
            Custom logger instance. If None, uses module logger.
        index_context : SpladeIndexContext | None, optional
            Context for index management. If None, uses production context.
        """
        self._logger = logger_ or logging.getLogger(__name__)
        self._repo_root = Path(app_config.paths.repo_root).expanduser().resolve()
        self._config: SpladeSettings = app_config.splade
        self._index_context = index_context or SpladeIndexContext.production()

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
        self._index_context.subprocess_runner(cmd, env_overrides)

        metadata_path = vectors_dir / ENCODING_METADATA_FILENAME
        corpus_digest = None
        doc_count: int | None = None
        if metadata_path.exists():
            metadata = msgspec.json.decode(metadata_path.read_bytes(), type=SpladeEncodingMetadata)
            doc_count = metadata.doc_count
            corpus_digest = metadata.source_path
        pyserini_version = self._index_context.version_provider()
        index_metadata = SpladeIndexMetadata(
            doc_count=doc_count,
            built_at=self._index_context.clock().isoformat(),
            vectors_dir=str(vectors_dir),
            corpus_digest=corpus_digest,
            pyserini_version=pyserini_version,
            threads=threads,
            index_dir=str(index_dir),
            index_size_bytes=self._index_context.directory_size(index_dir),
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
    "SPLADEEngine",
    "SpladeArtifactMetadata",
    "SpladeArtifactsManager",
    "SpladeBuildOptions",
    "SpladeEncodeOptions",
    "SpladeEncodingMetadata",
    "SpladeEncodingSummary",
    "SpladeExportOptions",
    "SpladeExportSummary",
    "SpladeHit",
    "SpladeIndexManager",
    "SpladeIndexMetadata",
    "SpladeQueryEngine",
    "SpladeQueryOptions",
]
