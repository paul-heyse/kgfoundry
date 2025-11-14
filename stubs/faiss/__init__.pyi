from collections.abc import Sequence

class VectorTransform:
    ...


class Index:
    ntotal: int
    d: int
    nprobe: int

    def __init__(self, *args: object, **kwargs: object) -> None: ...

    def add(self, vectors: object) -> None: ...

    def add_with_ids(self, vectors: object, ids: object) -> None: ...

    def reset(self) -> None: ...

    def search(self, vectors: object, k: int) -> object: ...

    def reconstruct(self, idx: int) -> object: ...

    def make_direct_map(self) -> None: ...


class IndexIDMap2(Index):
    index: Index

    def __init__(self, index: Index) -> None: ...

    def add_with_ids(self, vectors: Sequence[Sequence[float]], ids: Sequence[int]) -> None: ...


class IndexFlatIP(Index):
    ...


class IndexIVFFlat(Index):
    ...


class IndexFlatL2(Index):
    ...


class StandardGpuResources:
    def __init__(self, *args: object, **kwargs: object) -> None: ...


class GpuClonerOptions:
    use_cuvs: bool

    def __init__(self, *args: object, **kwargs: object) -> None: ...


__all__ = [
    "GpuClonerOptions",
    "Index",
    "IndexFlatIP",
    "IndexFlatL2",
    "IndexIDMap2",
    "IndexIVFFlat",
    "StandardGpuResources",
    "VectorTransform",
]
