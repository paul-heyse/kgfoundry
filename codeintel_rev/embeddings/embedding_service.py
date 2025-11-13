"""Embedding provider abstractions for chunk ingestion and runtime services."""

from __future__ import annotations

import hashlib
import queue
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import Future
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from codeintel_rev.config.settings import EmbeddingsConfig, IndexConfig, Settings, VLLMConfig
from codeintel_rev.io.vllm_engine import InprocessVLLMEmbedder
from codeintel_rev.typing import NDArrayF32, gate_import
from kgfoundry_common.logging import get_logger
from kgfoundry_common.prometheus import build_counter, build_gauge, build_histogram

LOGGER = get_logger(__name__)

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
        """Return a JSON-serialisable dictionary."""
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

    def embed_stream(
        self, texts: Iterable[str], *, chunk_size: int | None = None
    ) -> Iterable[NDArrayF32]:
        """Embed a potentially large iterator, yielding one matrix per chunk."""

    @property
    def metadata(self) -> EmbeddingMetadata:
        """Return static provider metadata."""

    def fingerprint(self) -> str:
        """Return a stable fingerprint suitable for manifests and checksums."""

    def close(self) -> None:
        """Release provider resources."""


def _numpy() -> object:
    return gate_import("numpy", "embedding provider vector operations")


def _l2_normalize(vectors: NDArrayF32) -> NDArrayF32:
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


class _BoundedBatchExecutor:
    """Opportunistically coalesces pending embedding jobs into micro-batches."""

    def __init__(
        self,
        *,
        micro_batch: int,
        max_pending: int,
        max_wait_ms: int,
        emit: Callable[[Sequence[str]], NDArrayF32],
    ) -> None:
        if micro_batch <= 0:
            raise EmbeddingConfigError("micro_batch must be positive")
        self._emit = emit
        self._micro_batch = micro_batch
        self._queue: queue.Queue[_ExecutorJob | None] = queue.Queue(max(max_pending, 1))
        self._max_wait = max(max_wait_ms, 1) / 1000.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="embedding-batcher", daemon=True)
        self._thread.start()

    def submit(self, texts: list[str]) -> NDArrayF32:
        """Enqueue ``texts`` and block until the fused batch completes."""
        if self._stop.is_set():
            raise EmbeddingRuntimeError("Embedding executor stopped")
        future: Future[NDArrayF32] = Future()
        job = _ExecutorJob(texts=texts, future=future)
        self._queue.put(job)
        return future.result()

    def close(self) -> None:
        """Stop the background worker and drain the queue."""
        self._stop.set()
        self._queue.put(None)
        self._thread.join(timeout=1)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if job is None:
                break
            jobs = [job]
            fused: list[str] = list(job.texts)
            start = time.perf_counter()
            while len(fused) < self._micro_batch:
                wait_remaining = self._max_wait - (time.perf_counter() - start)
                if wait_remaining <= 0:
                    break
                try:
                    next_job = self._queue.get(timeout=wait_remaining)
                except queue.Empty:
                    break
                if next_job is None:
                    self._stop.set()
                    break
                jobs.append(next_job)
                fused.extend(next_job.texts)
                if self._stop.is_set():
                    break
            try:
                result = self._emit(fused)
            except Exception as exc:  # pragma: no cover - propagated
                for job_item in jobs:
                    job_item.future.set_exception(exc)
                continue
            offset = 0
            for job_item in jobs:
                count = len(job_item.texts)
                job_item.future.set_result(result[offset : offset + count])
                offset += count


@dataclass(slots=True)
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
        if self._state.fingerprint is None:
            payload = (
                f"{self.metadata.provider}:{self.metadata.model_name}:{self.metadata.dimension}"
            )
            digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            self._state.fingerprint = digest
        return self._state.fingerprint

    def close(self) -> None:
        executor = self._executor
        if executor is not None:
            executor.close()
        self._close_impl()

    # ------------------------------------------------------------------ helpers
    def _embed_direct(self, texts: Sequence[str]) -> NDArrayF32:
        if not texts:
            np = _numpy()
            return np.zeros((0, self._state.index.vec_dim), dtype=np.float32)
        with self._inflight_guard():
            start = time.perf_counter()
            try:
                batch, token_count = self._run_inference(texts)
            except Exception as exc:  # pragma: no cover - propagated to caller
                _ERROR_COUNTER.labels(
                    provider=self._state.provider_name, reason=exc.__class__.__name__
                ).inc()
                raise
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
        if array.ndim != 2:
            raise EmbeddingRuntimeError(f"Expected 2D embeddings, received shape {array.shape}")
        if self._state.normalize:
            array = _l2_normalize(array)
        vec_dim = array.shape[1]
        if self._state.dimension is None:
            self._state.dimension = vec_dim
            if vec_dim != self._state.index.vec_dim:
                raise EmbeddingRuntimeError(
                    f"Embedding dimension mismatch: expected {self._state.index.vec_dim}, observed {vec_dim}",
                )
        elif vec_dim != self._state.dimension:
            raise EmbeddingRuntimeError(
                f"Inconsistent embedding dimensions: {self._state.dimension} vs {vec_dim}",
            )
        self.metadata  # ensure cache populated with detected dimension
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
    def _inflight_guard(self):
        with self._gauge_lock:
            self._inflight += 1
            _INFLIGHT.labels(provider=self._state.provider_name).set(self._inflight)
        try:
            yield
        finally:
            with self._gauge_lock:
                self._inflight = max(self._inflight - 1, 0)
                _INFLIGHT.labels(provider=self._state.provider_name).set(self._inflight)

    def _memory_bytes(self) -> int:
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


def get_embedding_provider(settings: Settings, *, prefer: str | None = None) -> EmbeddingProvider:
    """Return the configured embedding provider, falling back when allowed."""
    provider_name = (prefer or settings.embeddings.provider).lower()
    if provider_name == "hf":
        try:
            return HFEmbeddingProvider(embeddings=settings.embeddings, index=settings.index)
        except Exception as exc:
            raise EmbeddingRuntimeError(f"Failed to initialize HF provider: {exc}") from exc
    if provider_name != "vllm":
        raise EmbeddingConfigError(
            f"Unsupported embedding provider: {prefer or settings.embeddings.provider}"
        )
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
        torch_mod = gate_import("torch", "Hugging Face embedding provider")
        transformers_mod = gate_import("transformers", "Hugging Face embedding provider")
        self._torch = torch_mod
        self._transformers = transformers_mod
        device = embeddings.device
        if device == "auto":
            device = "cuda" if torch_mod.cuda.is_available() else "cpu"
        if device.startswith("cuda") and not torch_mod.cuda.is_available():
            raise EmbeddingRuntimeError("CUDA device requested but torch.cuda.is_unavailable()")
        self._device = torch_mod.device(device)
        super().__init__(provider_name="hf", config=embeddings, index=index, device_label=device)
        self._tokenizer = transformers_mod.AutoTokenizer.from_pretrained(
            embeddings.model_name,
            trust_remote_code=True,
        )
        self._model = transformers_mod.AutoModel.from_pretrained(
            embeddings.model_name,
            trust_remote_code=True,
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
        except Exception:  # pragma: no cover - telemetry best effort
            return 0
        return 0

    def _close_impl(self) -> None:
        # Best-effort cleanup to help CI memory pressure.
        try:
            del self._model
        except AttributeError:  # pragma: no cover - defensive
            pass
        if self._device.type == "cuda":
            try:
                self._torch.cuda.empty_cache()
            except Exception:  # pragma: no cover - telemetry best effort
                LOGGER.debug("torch.cuda.empty_cache failed", exc_info=True)
