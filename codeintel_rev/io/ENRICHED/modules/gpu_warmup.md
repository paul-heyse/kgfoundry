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
- from **typing** import TYPE_CHECKING, Any, SupportsInt, cast
- from **codeintel_rev.metrics.registry** import GPU_AVAILABLE, GPU_TEMP_SCRATCH_BYTES
- from **codeintel_rev.typing** import gate_import
- from **kgfoundry_common.logging** import get_logger
- from **(absolute)** import faiss
- from **(absolute)** import torch

## Definitions

- function: `_check_cuda_availability` (line 32)
- function: `_check_faiss_gpu_support` (line 68)
- function: `_test_torch_gpu_operations` (line 101)
- function: `_test_faiss_gpu_resources` (line 127)
- function: `warmup_gpu` (line 159)

## Tags

overlay-needed, public-api
