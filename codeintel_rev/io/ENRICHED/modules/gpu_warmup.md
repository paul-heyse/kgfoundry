# app/gpu_warmup.py

## Docstring

```
GPU warmup and initialization sequence.

Performs comprehensive GPU availability checks and warmup operations to ensure
GPU is reachable and functional before expensive operations begin.
```

## Imports

- from **__future__** import annotations
- from **functools** import lru_cache
- from **typing** import SupportsInt, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.metrics.registry** import GPU_AVAILABLE, GPU_TEMP_SCRATCH_BYTES
- from **codeintel_rev.typing** import FaissModule, NumpyModule, TorchModule, gate_import
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 17)
- variable: `np` (line 25)
- function: `_check_cuda_availability` (line 28)
- function: `_check_faiss_gpu_support` (line 64)
- function: `_test_torch_gpu_operations` (line 97)
- function: `_test_faiss_gpu_resources` (line 123)
- function: `warmup_gpu` (line 155)

## Dependency Graph

- **fan_in**: 1
- **fan_out**: 3
- **cycle_group**: 19

## Declared Exports (__all__)

warmup_gpu

## Tags

public-api
