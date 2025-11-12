from __future__ import annotations

from typing import Any

from codeintel_rev.app.config_context import ApplicationContext


class Capabilities:
    faiss_index: bool
    duckdb: bool
    scip_index: bool
    vllm_client: bool
    coderank_index_present: bool
    warp_index_present: bool
    xtr_index_present: bool
    faiss_importable: bool
    duckdb_importable: bool
    httpx_importable: bool
    torch_importable: bool
    lucene_importable: bool
    onnxruntime_importable: bool
    faiss_gpu_available: bool
    faiss_gpu_disabled_reason: str | None
    active_index_version: str | None
    versions_available: int

    def __init__(
        self,
        *,
        faiss_index: bool = ...,
        duckdb: bool = ...,
        scip_index: bool = ...,
        vllm_client: bool = ...,
        coderank_index_present: bool = ...,
        warp_index_present: bool = ...,
        xtr_index_present: bool = ...,
        faiss_importable: bool = ...,
        duckdb_importable: bool = ...,
        httpx_importable: bool = ...,
        torch_importable: bool = ...,
        lucene_importable: bool = ...,
        onnxruntime_importable: bool = ...,
        faiss_gpu_available: bool = ...,
        faiss_gpu_disabled_reason: str | None = ...,
        active_index_version: str | None = ...,
        versions_available: int = ...,
    ) -> None: ...

    @property
    def has_semantic(self) -> bool: ...

    @property
    def has_symbols(self) -> bool: ...

    @property
    def has_reranker(self) -> bool: ...

    def model_dump(self) -> dict[str, object]: ...

    def stamp(self, payload: dict[str, object] | None = None) -> str: ...

    @classmethod
    def from_context(cls, context: ApplicationContext) -> Capabilities: ...


__all__ = ["Capabilities"]
