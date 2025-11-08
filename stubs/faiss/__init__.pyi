import numpy as np

METRIC_INNER_PRODUCT: int

class Index:
    nprobe: int

    def train(self, vectors: np.ndarray, /) -> None: ...
    def add_with_ids(self, vectors: np.ndarray, ids: np.ndarray, /) -> None: ...
    def search(self, vectors: np.ndarray, k: int, /) -> tuple[np.ndarray, np.ndarray]: ...

class IndexIDMap2(Index):
    def __init__(self, index: Index, /) -> None: ...

class StandardGpuResources:
    def __init__(self) -> None: ...

class GpuClonerOptions:
    useFloat16: bool  # noqa: N815
    use_cuvs: bool

    def __init__(self) -> None: ...

def normalize_L2(vectors: np.ndarray, /) -> None: ...  # noqa: N802
def index_factory(dimension: int, description: str, metric: int, /) -> Index: ...
def write_index(index: Index, path: str, /) -> None: ...
def read_index(path: str, /) -> Index: ...
def index_cpu_to_gpu(
    resources: StandardGpuResources,
    device: int,
    index: Index,
    options: GpuClonerOptions,
    /,
) -> Index: ...
