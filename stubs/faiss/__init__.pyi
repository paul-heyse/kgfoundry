from collections.abc import Sequence
from os import PathLike
from typing import overload

import numpy as np
from numpy.typing import NDArray

type Float32Array = NDArray[np.float32]
type Float64Array = NDArray[np.float64]
type Int64Array = NDArray[np.int64]

METRIC_INNER_PRODUCT: int
METRIC_L2: int

class Index:
    d: int
    ntotal: int
    nprobe: int
    is_trained: bool

    def __init__(self, *args: object, **kwargs: object) -> None: ...
    def train(self, vectors: Float32Array, /) -> None: ...
    def add(self, vectors: Float32Array, /) -> None: ...
    def add_with_ids(self, vectors: Float32Array, ids: Int64Array, /) -> None: ...
    def search(self, vectors: Float32Array, k: int, /) -> tuple[Float32Array, Int64Array]: ...
    def range_search(
        self, vectors: Float32Array, radius: float, /
    ) -> tuple[int, Float32Array, Int64Array]: ...
    def reset(self) -> None: ...
    def reconstruct(self, index: int, /) -> Float32Array: ...

class IndexFlat(Index): ...
class IndexFlatIP(IndexFlat): ...
class IndexFlatL2(IndexFlat): ...

class IndexIVFFlat(Index):
    nlist: int

    def __init__(self, quantizer: Index, d: int, nlist: int, metric: int, /) -> None: ...

class IndexIVFPQ(Index):
    nlist: int

    def __init__(
        self, quantizer: Index, d: int, nlist: int, m: int, bits: int, metric: int, /
    ) -> None: ...

class IndexIDMap(Index):
    index: Index

    def __init__(self, index: Index, /) -> None: ...

class IndexIDMap2(IndexIDMap):
    def contains(self, ident: int, /) -> bool: ...
    def search(self, ident: int, /) -> int: ...
    def find(self, ident: int, /) -> int: ...
    def at(self, position: int, /) -> int: ...

class StandardGpuResources:
    def __init__(self) -> None: ...

class GpuClonerOptions:
    useFloat16: bool  # noqa: N815
    useFloat16CoarseQuantizer: bool  # noqa: N815
    useFloat16LookupTables: bool  # noqa: N815
    usePrecomputed: bool  # noqa: N815
    reserveVecs: int
    indicesOptions: int
    use_cuvs: bool

    def __init__(self) -> None: ...

class GpuIndexFlatIP(Index): ...

def get_num_gpus() -> int: ...
def normalize_L2(vectors: Float32Array, /) -> None: ...  # noqa: N802
def estimate_memory(index: Index) -> float: ...
def write_index(index: Index, path: str | PathLike[str], /) -> None: ...
def read_index(path: str | PathLike[str], /) -> Index: ...
def index_factory(dimension: int, description: str, metric: int, /) -> Index: ...
def index_cpu_to_gpu(
    resources: StandardGpuResources,
    device: int,
    index: Index,
    options: GpuClonerOptions | None,
    /,
) -> Index: ...
def index_gpu_to_cpu(index: Index, /) -> Index: ...
def index_to_array(index: Index, /) -> Float32Array: ...
def array_to_index(vectors: Float32Array, /) -> Index: ...
def reconstruct_n(index: Index, start: int, count: int, /) -> Float32Array: ...
def knn_gpu(
    resources: StandardGpuResources,
    queries: Float32Array,
    database: Float32Array,
    k: int,
    /,
    *,
    metric: int = ...,
    use_cuvs: bool | None = None,
) -> tuple[Float32Array, Int64Array]: ...
@overload
def range_search_gpu(
    resources: StandardGpuResources,
    queries: Float32Array,
    database: Float32Array,
    radius: float,
    /,
    *,
    metric: int = ...,
    use_cuvs: bool | None = None,
) -> tuple[Int64Array, Float32Array, Int64Array]: ...
@overload
def range_search_gpu(
    resources: StandardGpuResources,
    queries: Float32Array,
    database: Float64Array,
    radius: float,
    /,
    *,
    metric: int = ...,
    use_cuvs: bool | None = None,
) -> tuple[Int64Array, Float64Array, Int64Array]: ...
def index_cpu_to_all_gpus(
    resources: StandardGpuResources,
    devices: Sequence[int],
    index: Index,
    options: GpuClonerOptions | None,
    /,
) -> list[Index]: ...
