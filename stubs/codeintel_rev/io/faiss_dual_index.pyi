from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence


class IndexManifest:
    version: str
    vec_dim: int
    index_type: str
    metric: str
    trained_on: str
    built_at: str
    gpu_enabled: bool
    primary_count: int
    secondary_count: int
    nlist: int | None
    pq_m: int | None
    cuvs_version: str | None

    def __init__(
        self,
        *,
        version: str,
        vec_dim: int,
        index_type: str,
        metric: str,
        trained_on: str,
        built_at: str,
        gpu_enabled: bool,
        primary_count: int,
        secondary_count: int,
        nlist: int | None = None,
        pq_m: int | None = None,
        cuvs_version: str | None = None,
    ) -> None: ...

    @classmethod
    def from_file(cls, path: Path) -> IndexManifest: ...

    def to_file(self, path: Path) -> None: ...


class FAISSDualIndexManager:
    def __init__(self, index_dir: Path, settings: Any, vec_dim: int) -> None: ...

    def set_test_indexes(self, primary: Any | None, secondary: Any | None) -> None: ...

    @property
    def gpu_enabled(self) -> bool: ...

    @property
    def gpu_disabled_reason(self) -> str | None: ...

    @property
    def primary_index(self) -> Any | None: ...

    @property
    def secondary_index(self) -> Any | None: ...

    @property
    def manifest(self) -> IndexManifest | None: ...

    async def ensure_ready(self) -> tuple[bool, str | None]: ...

    async def close(self) -> None: ...

    async def search(self, queries: Any, k: int) -> tuple[Any, Any]: ...

    async def add_incremental(self, vectors: Any, ids: Sequence[int]) -> None: ...

    def needs_compaction(self) -> bool: ...

    async def try_gpu_clone(self) -> bool: ...


__all__ = ["FAISSDualIndexManager", "IndexManifest"]
