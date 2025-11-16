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
- from **codeintel_rev.typing** import FaissModule, NumpyModule, TorchModule, gate_import
- from **kgfoundry_common.logging** import get_logger

## Definitions

- variable: `LOGGER` (line 16)
- variable: `np` (line 24)
- function: `_check_cuda_availability` (line 27)
- function: `_check_faiss_gpu_support` (line 63)
- function: `_test_torch_gpu_operations` (line 96)
- function: `_test_faiss_gpu_resources` (line 122)
- function: `warmup_gpu` (line 154)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 2
- **cycle_group**: 29

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 19
- recent churn 90: 19

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

warmup_gpu

## Doc Health

- **summary**: GPU warmup and initialization sequence.
- has summary: yes
- param parity: yes
- examples present: yes

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Config References

- app/hypercorn.toml

## Hotspot

- score: 2.00

## Side Effects

- none detected

## Complexity

- branches: 18
- cyclomatic: 19
- loc: 252

## Doc Coverage

- `_check_cuda_availability` (function): summary=yes, params=ok, examples=no — Check CUDA availability via PyTorch.
- `_check_faiss_gpu_support` (function): summary=yes, params=ok, examples=no — Check FAISS GPU support.
- `_test_torch_gpu_operations` (function): summary=yes, params=ok, examples=no — Test basic GPU tensor operations using PyTorch.
- `_test_faiss_gpu_resources` (function): summary=yes, params=ok, examples=no — Test FAISS GPU resource initialization.
- `warmup_gpu` (function): summary=yes, params=ok, examples=yes — Perform GPU warmup sequence to verify GPU availability and functionality.

## Tags

low-coverage, public-api
