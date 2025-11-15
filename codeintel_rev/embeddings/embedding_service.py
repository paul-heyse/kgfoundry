"""Embedding provider abstractions for chunk ingestion and runtime services."""

from __future__ import annotations

import hashlib
import queue
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import Future
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from types import ModuleType, TracebackType
from typing import Any, Protocol, Self, cast, runtime_checkable

from codeintel_rev.config.settings import EmbeddingsConfig, IndexConfig, Settings, VLLMConfig
from codeintel_rev.io.vllm_engine import InprocessVLLMEmbedder
from codeintel_rev.telemetry.otel_metrics import build_counter, build_gauge, build_histogram
from codeintel_rev.typing import NDArrayF32, gate_import
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)
EMBEDDING_RANK = 2

_LATENCY = build_histogram(
    "embedding_latency_seconds",
    "Latency per embedding batch",
    labelnames=("provider", "device"),
)
_BATCH_SIZE = build_histogram(
    "embedding_batch_size",
    "Items per embedding batch",
    labelnames=("provider",),
)
_BATCH_COUNTER = build_counter(
    "embeddings_total",
    "Total embedding batches completed",
    labelnames=("provider",),
)
_ERROR_COUNTER = build_counter(
    "embedding_errors_total",
    "Embedding batch failures",
    labelnames=("provider", "reason"),
)
_INFLIGHT = build_gauge(
    "embedding_inflight_batches",
    "In-flight embedding batches",
    labelnames=("provider",),
)


class EmbeddingRuntimeError(RuntimeError):
    """Raised when an embedding provider fails to run."""


class EmbeddingConfigError(ValueError):
    """Raised when embedding configuration is invalid."""


@dataclass(frozen=True)
class EmbeddingMetadata:
    """Structured metadata describing the active embedding provider."""

    provider: str
    model_name: str
    dimension: int
    dtype: str
    normalize: bool
    device: str

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable dictionary.

        Returns
        -------
        dict[str, object]
            Provider metadata mapped to primitive types.
        """
        return {
            "provider": self.provider,
            "model_name": self.model_name,
            "dimension": self.dimension,
            "dtype": self.dtype,
            "normalize": self.normalize,
            "device": self.device,
        }


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Common surface for embedding providers used across CLIs and services."""

    def embed_texts(self, texts: Sequence[str]) -> NDArrayF32:
        """Embed a short batch of texts and return a dense matrix."""
        ...

    def embed_stream(
        self, texts: Iterable[str], *, chunk_size: int | None = None
    ) -> Iterable[NDArrayF32]:
        """Embed a potentially large iterator, yielding one matrix per chunk."""
        ...

    @property
    def metadata(self) -> EmbeddingMetadata:
        """Return static provider metadata."""
        ...

    def fingerprint(self) -> str:
        """Return a stable fingerprint suitable for manifests and checksums."""
        ...

    def close(self) -> None:
        """Release provider resources."""
        ...


def _numpy() -> ModuleType:
    """Return the lazily imported NumPy module for vector ops.

    Returns
    -------
    ModuleType
        The ``numpy`` module resolved via the typing gate.
    """
    return cast("ModuleType", gate_import("numpy", "embedding provider vector operations"))


def _l2_normalize(vectors: NDArrayF32) -> NDArrayF32:
    """Return vectors scaled to unit length along axis 1.

    This function normalizes input vectors to unit length using L2 (Euclidean)
    norm. Each row vector is scaled so that its L2 norm equals 1.0, ensuring
    all vectors have the same magnitude for consistent similarity computation.
    Zero vectors are handled by setting their norm to 1.0 to avoid division
    by zero.

    Parameters
    ----------
    vectors : NDArrayF32
        Input vectors with shape `(N, dim)` and dtype float32. Each row represents
        a vector to normalize. The function computes L2 norm along axis 1 (per row)
        and scales each vector to unit length.

    Returns
    -------
    NDArrayF32
        Normalized vectors with the same shape as ``vectors`` and dtype float32.
        Each row vector has L2 norm of 1.0 (unit length). Zero vectors are
        preserved as zero vectors (norm set to 1.0 to avoid division by zero).
    """
    np = _numpy()
    arr = np.asarray(vectors, dtype=np.float32)
    if not arr.size:
        return arr
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return arr / norms


@dataclass(slots=True, frozen=True)
class _ExecutorJob:
    texts: list[str]
    future: Future[NDArrayF32]


class _FailureCounter:
    """Increment error counters when an exception bubbles out of a context."""

    def __init__(self, provider_name: str) -> None:
        self._provider_name = provider_name

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> bool:
        if exc_type is not None:
            reason = exc_type.__name__
            _ERROR_COUNTER.labels(provider=self._provider_name, reason=reason).inc()
        return False


class _BatchResultHandler:
    """Resolve futures when a fused batch completes or fails."""

    def __init__(self, jobs: Sequence[_ExecutorJob]) -> None:
        self._jobs = list(jobs)

    def __enter__(self) -> Self:
        return self

    def set_result(self, result: NDArrayF32) -> None:
        """Distribute fused batch result to individual job futures.

        This method splits a fused batch result (containing embeddings for multiple
        jobs) into individual slices and sets each job's future with its corresponding
        portion. The method maintains the order of jobs and ensures each future
        receives the correct slice of embeddings aligned with its input texts.

        Parameters
        ----------
        result : NDArrayF32
            Fused embedding matrix with shape `(total_texts, dim)` containing
            embeddings for all texts from all jobs in sequence. The matrix is
            split sequentially, with each job receiving a contiguous slice
            corresponding to its input texts.

        Notes
        -----
        This method is called when a fused batch completes successfully. It
        distributes the result to all pending futures, allowing callers to
        retrieve their embeddings. The method assumes the result matrix is
        correctly sized to match the total number of texts across all jobs.
        Time complexity: O(n) where n is the number of jobs. Thread-safe if
        Future.set_result() is thread-safe.
        """
        offset = 0
        for job in self._jobs:
            count = len(job.texts)
            job.future.set_result(result[offset : offset + count])
            offset += count

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> bool:
        if exc_type is None:
            return False
        error = (
            exc if isinstance(exc, Exception) else EmbeddingRuntimeError("Embedding batch failed")
        )
        for job in self._jobs:
            job.future.set_exception(error)
        LOGGER.error("embedding.batch_failed", extra={"error": str(error)})
        return True


class _QueueSentinel:
    """Unique sentinel signaling executor shutdown."""


class _BoundedBatchExecutor:
    """Opportunistically coalesces pending embedding jobs into micro-batches."""

    _SENTINEL = _QueueSentinel()

    def __init__(
        self,
        *,
        micro_batch: int,
        max_pending: int,
        max_wait_ms: int,
        emit: Callable[[Sequence[str]], NDArrayF32],
    ) -> None:
        if micro_batch <= 0:
            msg = "micro_batch must be positive"
            raise EmbeddingConfigError(msg)
        self._emit = emit
        self._micro_batch = micro_batch
        self._queue: queue.Queue[_ExecutorJob | _QueueSentinel] = queue.Queue(max(max_pending, 1))
        self._max_wait = max(max_wait_ms, 1) / 1000.0
        self._stop = threading.Event()
        self._sentinel: _QueueSentinel = self._SENTINEL
        self._thread = threading.Thread(target=self._run, name="embedding-batcher", daemon=True)
        self._thread.start()

    def submit(self, texts: list[str]) -> NDArrayF32:
        """Enqueue ``texts`` and block until the fused batch completes.

        This method submits a batch of texts to the background executor for
        embedding generation. The texts are enqueued and may be fused with other
        pending batches to improve throughput. The method blocks until the batch
        completes and embeddings are available.

        Parameters
        ----------
        texts : list[str]
            List of text strings to embed. The texts are enqueued as a job and
            processed by the background executor. The texts may be fused with
            other pending batches if micro-batching is enabled.

        Returns
        -------
        NDArrayF32
            Embedding matrix with shape `(len(texts), dim)` aligned with the
            input texts. Dtype is float32. The embeddings are generated by the
            background executor and returned once the batch completes.

        Raises
        ------
        EmbeddingRuntimeError
            Raised when the executor has already been stopped. The executor
            cannot accept new jobs after close() has been called.
        """
        if self._stop.is_set():
            msg = "Embedding executor stopped"
            raise EmbeddingRuntimeError(msg)
        future: Future[NDArrayF32] = Future()
        job = _ExecutorJob(texts=texts, future=future)
        self._queue.put(job)
        return future.result()

    def close(self) -> None:
        """Stop the background worker and drain the queue."""
        self._stop.set()
        self._queue.put(self._sentinel)
        self._thread.join(timeout=1)

    def _run(self) -> None:
        while not self._stop.is_set():
            job = self._next_job()
            if job is None:
                continue
            jobs = self._gather_jobs(job)
            fused = [text for item in jobs for text in item.texts]
            with _BatchResultHandler(jobs) as handler:
                vectors = self._emit(fused)
                handler.set_result(vectors)

    def _next_job(self) -> _ExecutorJob | None:
        try:
            item = self._queue.get(timeout=0.1)
        except queue.Empty:
            return None
        if isinstance(item, _QueueSentinel):
            self._stop.set()
            return None
        return item

    def _gather_jobs(self, first_job: _ExecutorJob) -> list[_ExecutorJob]:
        jobs = [first_job]
        fused_size = len(first_job.texts)
        start = time.perf_counter()
        while fused_size < self._micro_batch:
            wait_remaining = self._max_wait - (time.perf_counter() - start)
            if wait_remaining <= 0:
                break
            next_job = self._fetch_with_timeout(wait_remaining)
            if next_job is None:
                break
            jobs.append(next_job)
            fused_size += len(next_job.texts)
        return jobs

    def _fetch_with_timeout(self, timeout: float) -> _ExecutorJob | None:
        try:
            item = self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
        if isinstance(item, _QueueSentinel):
            self._stop.set()
            return None
        return item


@dataclass(slots=True, frozen=False)
class _ProviderState:
    config: EmbeddingsConfig
    index: IndexConfig
    provider_name: str
    device_label: str
    dtype: str = "float32"
    normalize: bool = True
    dimension: int | None = None
    metadata: EmbeddingMetadata | None = None
    fingerprint: str | None = None


class _ProviderBase(EmbeddingProvider):
    """Shared batching/metrics logic used by concrete providers."""

    def __init__(
        self,
        *,
        provider_name: str,
        config: EmbeddingsConfig,
        index: IndexConfig,
        device_label: str,
    ) -> None:
        self._state = _ProviderState(
            config=config,
            index=index,
            provider_name=provider_name,
            device_label=device_label,
            normalize=config.normalize,
        )
        self._executor: _BoundedBatchExecutor | None = None
        if config.max_pending_batches > 0:
            self._executor = _BoundedBatchExecutor(
                micro_batch=max(config.micro_batch_size, 1),
                max_pending=config.max_pending_batches,
                max_wait_ms=config.max_wait_ms,
                emit=self._embed_direct,
            )
        self._gauge_lock = threading.Lock()
        self._inflight = 0

    def embed_texts(self, texts: Sequence[str]) -> NDArrayF32:
        """Embed short batches of texts synchronously.

        This method generates embeddings for a batch of text inputs. For small
        batches (within configured batch_size), the method may use the background
        executor for micro-batching if enabled. For larger batches or when the
        executor is disabled, embeddings are generated directly. The method
        sanitizes inputs (truncating long texts) and returns normalized embeddings
        if configured.

        Parameters
        ----------
        texts : Sequence[str]
            Sequence of text strings to embed. Each string is tokenized and passed
            through the embedding model to generate a dense vector representation.
            Texts exceeding max_sequence_chars are truncated.

        Returns
        -------
        NDArrayF32
            Embedding matrix with shape `(len(texts), dim)` aligned with the input
            texts. Dtype is float32. Embeddings are normalized if the normalize
            configuration is enabled, otherwise raw model outputs. Empty input
            returns a zero matrix with shape `(0, vec_dim)`.
        """
        payload = self._sanitize(texts)
        if not payload:
            np = _numpy()
            return np.zeros((0, self._state.index.vec_dim), dtype=np.float32)
        executor = self._executor
        if executor is not None and len(payload) <= self._state.config.batch_size:
            return executor.submit(payload)
        return self._embed_direct(payload)

    def embed_stream(
        self,
        texts: Iterable[str],
        *,
        chunk_size: int | None = None,
    ) -> Iterable[NDArrayF32]:
        """Yield embeddings over ``texts`` in streaming batches.

        This method processes a potentially large iterable of texts in streaming
        fashion, yielding embedding matrices for each batch. The method buffers
        texts until the chunk size is reached, then generates embeddings and
        yields the result. This enables memory-efficient processing of large
        text collections without loading everything into memory.

        Parameters
        ----------
        texts : Iterable[str]
            Iterable of text strings to embed. The texts are processed in batches,
            with each batch yielding an embedding matrix. The iterable is consumed
            lazily, enabling memory-efficient processing of large collections.
        chunk_size : int | None, optional
            Number of texts per batch (defaults to configured batch_size). Controls
            the size of each embedding matrix yielded. Larger chunks improve
            throughput but increase memory usage.

        Yields
        ------
        NDArrayF32
            Embedding matrix per chunk with shape `(batch, dim)` where batch is
            the number of texts in the chunk (up to chunk_size). Dtype is float32.
            Embeddings are normalized if configured. The final chunk may be smaller
            than chunk_size if the input iterable is exhausted.
        """
        buffer: list[str] = []
        final_chunk = chunk_size or self._state.config.batch_size
        for text in texts:
            buffer.append(text)
            if len(buffer) >= final_chunk:
                yield self._embed_direct(self._sanitize(buffer))
                buffer.clear()
        if buffer:
            yield self._embed_direct(self._sanitize(buffer))

    @property
    def metadata(self) -> EmbeddingMetadata:
        """Return static provider metadata.

        This property returns cached provider metadata describing the embedding
        provider configuration. The metadata includes provider name, model name,
        embedding dimension, dtype, normalization settings, and device information.
        The metadata is computed lazily on first access and cached for subsequent
        calls.

        Returns
        -------
        EmbeddingMetadata
            Immutable metadata object containing:
            - provider: Provider name (e.g., "vllm", "hf")
            - model_name: Model identifier from configuration
            - dimension: Embedding dimension (detected or configured)
            - dtype: Data type string (e.g., "float32")
            - normalize: Whether embeddings are L2-normalized
            - device: Device label (e.g., "cuda", "cpu")

        Notes
        -----
        The metadata is cached in the provider state after first computation.
        If dimension is not yet detected, uses the configured index vector
        dimension. The metadata is used for logging, telemetry, and provider
        identification. Thread-safe if state access is thread-safe.
        """
        meta = self._state.metadata
        if meta is None:
            dimension = self._state.dimension or self._state.index.vec_dim
            meta = EmbeddingMetadata(
                provider=self._state.provider_name,
                model_name=self._state.config.model_name,
                dimension=dimension,
                dtype=self._state.dtype,
                normalize=self._state.normalize,
                device=self._state.device_label,
            )
            self._state.metadata = meta
        return meta

    def fingerprint(self) -> str:
        """Return a stable fingerprint suitable for manifests and checksums.

        This method computes a deterministic fingerprint based on provider metadata
        (provider name, model name, and embedding dimension). The fingerprint is
        computed as a SHA-256 hash of the metadata string, providing a stable
        identifier that can be used for caching, manifest generation, and checksum
        validation. The fingerprint is cached after first computation.

        Returns
        -------
        str
            Hexadecimal SHA-256 hash string (64 characters) representing the
            provider configuration fingerprint. The fingerprint is deterministic
            for the same provider, model, and dimension combination, enabling
            stable identification across runs.

        Notes
        -----
        The fingerprint is computed from provider metadata (provider:model:dimension)
        and cached in the provider state. It is used for manifest generation,
        cache keys, and checksum validation. The fingerprint does not include
        runtime state or device information, ensuring consistency across different
        execution environments with the same configuration. Thread-safe if state
        access is thread-safe.
        """
        if self._state.fingerprint is None:
            payload = (
                f"{self.metadata.provider}:{self.metadata.model_name}:{self.metadata.dimension}"
            )
            digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            self._state.fingerprint = digest
        return self._state.fingerprint

    def close(self) -> None:
        """Release provider resources.

        This method performs cleanup operations to release provider resources,
        including stopping the background batch executor (if configured) and
        calling the implementation-specific cleanup hook. The method should be
        called when the provider is no longer needed to free memory, GPU
        resources, and background threads.

        Notes
        -----
        This method stops the background batch executor if one was created,
        which drains pending jobs and stops the worker thread. It then calls
        the implementation-specific _close_impl() hook for provider-specific
        cleanup (e.g., releasing model weights, clearing GPU cache). The method
        is idempotent and safe to call multiple times. After calling close(),
        the provider should not be used for further embedding operations.
        Thread-safe if executor and implementation cleanup are thread-safe.
        """
        executor = self._executor
        if executor is not None:
            executor.close()
        self._close_impl()

    # ------------------------------------------------------------------ helpers
    def _embed_direct(self, texts: Sequence[str]) -> NDArrayF32:
        if not texts:
            np = _numpy()
            return np.zeros((0, self._state.index.vec_dim), dtype=np.float32)
        with self._inflight_guard(), _FailureCounter(self._state.provider_name):
            start = time.perf_counter()
            batch, token_count = self._run_inference(texts)
            duration = time.perf_counter() - start
        vectors = self._post_process(batch)
        self._record_metrics(
            batch_size=len(texts),
            duration=duration,
            tokens=token_count,
            dimension=vectors.shape[1] if vectors.size else self._state.index.vec_dim,
        )
        return vectors

    def _post_process(self, vectors: NDArrayF32) -> NDArrayF32:
        np = _numpy()
        array = np.asarray(vectors, dtype=np.float32)
        if array.ndim != EMBEDDING_RANK:
            msg = f"Expected {EMBEDDING_RANK}D embeddings, received shape {array.shape}"
            raise EmbeddingRuntimeError(msg)
        if self._state.normalize:
            array = _l2_normalize(array)
        vec_dim = array.shape[1]
        if self._state.dimension is None:
            self._state.dimension = vec_dim
            if vec_dim != self._state.index.vec_dim:
                msg = (
                    "Embedding dimension mismatch: expected "
                    f"{self._state.index.vec_dim}, observed {vec_dim}"
                )
                raise EmbeddingRuntimeError(msg)
        elif vec_dim != self._state.dimension:
            msg = f"Inconsistent embedding dimensions: {self._state.dimension} vs {vec_dim}"
            raise EmbeddingRuntimeError(msg)
        _ = self.metadata  # ensure cache populated with detected dimension
        return array

    def _record_metrics(
        self, *, batch_size: int, duration: float, tokens: int, dimension: int
    ) -> None:
        provider = self._state.provider_name
        device = self._state.device_label
        if duration <= 0:
            duration = 1e-9
        token_rate = tokens / duration
        item_rate = batch_size / duration
        _LATENCY.labels(provider=provider, device=device).observe(duration)
        _BATCH_SIZE.labels(provider=provider).observe(batch_size)
        _BATCH_COUNTER.labels(provider=provider).inc()
        LOGGER.info(
            "embedding.batch",
            extra={
                "provider": provider,
                "device": device,
                "count": batch_size,
                "tokens": tokens,
                "token_rate": round(token_rate, 2),
                "item_rate": round(item_rate, 2),
                "duration_ms": round(duration * 1000, 2),
                "dimension": dimension,
                "mem_bytes": self._memory_bytes(),
            },
        )

    @contextmanager
    def _inflight_guard(self) -> Iterator[None]:
        """Track in-flight batches for Prometheus gauges."""
        with self._gauge_lock:
            self._inflight += 1
            _INFLIGHT.labels(provider=self._state.provider_name).set(self._inflight)
        try:
            yield
        finally:
            with self._gauge_lock:
                self._inflight = max(self._inflight - 1, 0)
                _INFLIGHT.labels(provider=self._state.provider_name).set(self._inflight)

    @staticmethod
    def _memory_bytes() -> int:
        return 0

    def _sanitize(self, texts: Sequence[str]) -> list[str]:
        max_chars = self._state.config.max_sequence_chars
        payload: list[str] = []
        for text in texts:
            if len(text) > max_chars:
                trimmed = text[:max_chars]
                LOGGER.debug(
                    "embedding.text_trimmed",
                    extra={
                        "provider": self._state.provider_name,
                        "original_len": len(text),
                        "trimmed_len": max_chars,
                    },
                )
                payload.append(trimmed)
            else:
                payload.append(text)
        return payload

    # ---------------------------------------------------------------- abstract hooks
    def _run_inference(self, texts: Sequence[str]) -> tuple[NDArrayF32, int]:
        raise NotImplementedError

    def _close_impl(self) -> None:
        """Allow subclasses to release resources."""


class VLLMProvider(_ProviderBase):
    """Embedding provider backed by the in-process vLLM engine."""

    def __init__(
        self,
        *,
        embeddings: EmbeddingsConfig,
        index: IndexConfig,
        vllm_config: VLLMConfig,
    ) -> None:
        super().__init__(
            provider_name="vllm",
            config=embeddings,
            index=index,
            device_label="cuda" if embeddings.device == "auto" else embeddings.device,
        )
        self._embedder = InprocessVLLMEmbedder(vllm_config)

    def _run_inference(self, texts: Sequence[str]) -> tuple[NDArrayF32, int]:
        return self._embedder.embed_batch_with_stats(texts)

    def _close_impl(self) -> None:
        self._embedder.close()


def get_embedding_provider(
    settings: Settings,
    *,
    prefer: str | None = None,
) -> EmbeddingProvider:
    """Return the configured embedding provider, falling back when allowed.

    This function creates and returns an embedding provider instance based on
    the provided settings. It supports multiple provider types (vLLM, HuggingFace)
    and can fall back to alternative providers when the preferred provider fails
    to initialize. The function handles provider initialization errors gracefully
    and provides fallback behavior when configured.

    Parameters
    ----------
    settings : Settings
        Application settings containing embedding configuration (provider name,
        model name, device, normalization, etc.) and index configuration (vector
        dimension). Used to initialize the selected provider.
    prefer : str | None, optional
        Preferred provider name to use instead of settings.embeddings.provider.
        If None, uses the configured provider from settings. Valid values are
        "vllm" or "hf" (case-insensitive). Used to override default provider
        selection.

    Returns
    -------
    EmbeddingProvider
        Concrete provider implementation (VLLMProvider or HFEmbeddingProvider)
        initialized with the provided settings. The provider is ready for use
        and can generate embeddings via embed_texts() or embed_stream().

    Raises
    ------
    EmbeddingConfigError
        Raised when the requested provider name is unsupported or invalid.
        Valid provider names are "vllm" and "hf" (case-insensitive).
    EmbeddingRuntimeError
        Raised when a provider fails to initialize and no fallback is allowed.
        For vLLM provider, falls back to HF if allow_hf_fallback is enabled.
        For HF provider, no fallback is available. Also raised when HF provider
        initialization fails and no fallback is configured. Wraps underlying
        provider initialization exceptions with context.
    Exception
        When vLLM provider initialization fails and allow_hf_fallback is False,
        the original exception from VLLMProvider initialization is re-raised
        (not wrapped) using a bare `raise` statement. This allows callers to
        handle provider-specific exceptions (e.g., CUDA errors, model loading
        failures) when fallback is disabled. The exception is re-raised using
        `raise` where the exception comes from the except block. Note: The
        exception is re-raised using a bare `raise`, so pydoclint may flag this
        as DOC502, but the exception is correctly propagated.

    Notes
    -----
    This function handles provider initialization errors gracefully. When vLLM
    provider initialization fails and allow_hf_fallback is True, it automatically
    falls back to HF provider. When fallback is disabled, provider-specific
    exceptions (e.g., CUDA errors, model loading failures, import errors) are
    re-raised directly. The function ensures at least one provider is available
    when fallback is enabled, or raises appropriate errors when no provider can
    be initialized.
    """
    provider_name = (prefer or settings.embeddings.provider).lower()
    if provider_name == "hf":
        try:
            return HFEmbeddingProvider(embeddings=settings.embeddings, index=settings.index)
        except Exception as exc:
            msg = f"Failed to initialize HF provider: {exc}"
            raise EmbeddingRuntimeError(msg) from exc
    if provider_name != "vllm":
        msg = f"Unsupported embedding provider: {prefer or settings.embeddings.provider}"
        raise EmbeddingConfigError(msg)
    try:
        return VLLMProvider(
            embeddings=settings.embeddings, index=settings.index, vllm_config=settings.vllm
        )
    except Exception as exc:
        if settings.embeddings.allow_hf_fallback:
            LOGGER.warning(
                "VLLM provider failed; falling back to HF",
                extra={"error": str(exc)},
            )
            return HFEmbeddingProvider(embeddings=settings.embeddings, index=settings.index)
        raise


class HFEmbeddingProvider(_ProviderBase):
    """CPU/GPU fallback using Hugging Face transformers."""

    def __init__(self, *, embeddings: EmbeddingsConfig, index: IndexConfig) -> None:
        torch_mod = cast("Any", gate_import("torch", "Hugging Face embedding provider"))
        transformers_mod = cast(
            "Any", gate_import("transformers", "Hugging Face embedding provider")
        )
        self._torch = torch_mod
        self._transformers = transformers_mod
        device = embeddings.device
        if device == "auto":
            device = "cuda" if torch_mod.cuda.is_available() else "cpu"
        if device.startswith("cuda") and not torch_mod.cuda.is_available():
            msg = "CUDA device requested but torch.cuda.is_unavailable()"
            raise EmbeddingRuntimeError(msg)
        self._device = torch_mod.device(device)
        super().__init__(provider_name="hf", config=embeddings, index=index, device_label=device)
        self._tokenizer = transformers_mod.AutoTokenizer.from_pretrained(
            embeddings.model_name,
            trust_remote_code=True,
        )
        torch_dtype = (
            torch_mod.float16 if self._device.type == "cuda" else torch_mod.float32
        )
        self._model = transformers_mod.AutoModel.from_pretrained(
            embeddings.model_name,
            trust_remote_code=True,
            torch_dtype=torch_dtype,
        )
        self._model.to(self._device)
        self._model.eval()

    def _run_inference(self, texts: Sequence[str]) -> tuple[NDArrayF32, int]:
        torch_mod = self._torch
        tokenizer = self._tokenizer
        model = self._model
        inputs = tokenizer(
            list(texts),
            padding=True,
            truncation=True,
            max_length=self._state.config.max_tokens,
            return_tensors="pt",
        )
        inputs = {k: v.to(self._device) for k, v in inputs.items()}
        with torch_mod.no_grad():
            outputs = model(**inputs)
        hidden_state = outputs.last_hidden_state
        pooled = hidden_state.mean(dim=1)
        vectors = pooled.detach().cpu().numpy().astype("float32", copy=False)
        attention_mask = inputs.get("attention_mask")
        if attention_mask is not None:
            tokens = int(attention_mask.sum().item())
        else:
            tokens = int(inputs["input_ids"].numel())
        return vectors, tokens

    def _memory_bytes(self) -> int:
        try:
            if self._device.type == "cuda":
                return int(self._torch.cuda.memory_allocated(self._device))
        except RuntimeError:  # pragma: no cover - telemetry best effort
            return 0
        return 0

    def _close_impl(self) -> None:
        """Release Hugging Face resources."""
        with suppress(AttributeError):  # pragma: no cover - defensive
            del self._model
        if self._device.type == "cuda":
            try:
                self._torch.cuda.empty_cache()
            except RuntimeError:  # pragma: no cover - telemetry best effort
                LOGGER.debug("torch.cuda.empty_cache failed", exc_info=True)


EmbeddingProviderBase = _ProviderBase
