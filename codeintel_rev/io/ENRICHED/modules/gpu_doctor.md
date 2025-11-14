# mcp_server/tools/gpu_doctor.py

## Docstring

```
GPU diagnostics script for PyTorch and FAISS.

Tiny GPU diagnostics for PyTorch and FAISS:
- Initializes CUDA context
- Runs a small GEMM in torch (cuBLAS path)
- Runs a tiny FAISS-GPU search (GpuIndexFlatIP)

Exits non-zero if --require-gpu is set and a GPU isn't usable.

Usage:
    python -m codeintel_rev.mcp_server.tools.gpu_doctor
    python -m codeintel_rev.mcp_server.tools.gpu_doctor --require-gpu
    python -m codeintel_rev.mcp_server.tools.gpu_doctor --torch-only
    python -m codeintel_rev.mcp_server.tools.gpu_doctor --faiss-only
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import argparse
- from **(absolute)** import sys
- from **(absolute)** import traceback
- from **typing** import cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.typing** import FaissModule, NumpyModule, TorchModule, gate_import

## Definitions

- variable: `np` (line 28)
- function: `check_torch` (line 31)
- function: `check_faiss` (line 91)
- function: `main` (line 144)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 2
- **cycle_group**: 146

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 8
- recent churn 90: 8

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: GPU diagnostics script for PyTorch and FAISS.
- has summary: yes
- param parity: yes
- examples present: no

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Hotspot

- score: 1.87

## Side Effects

- none detected

## Complexity

- branches: 17
- cyclomatic: 18
- loc: 197

## Doc Coverage

- `check_torch` (function): summary=yes, params=ok, examples=no — Check PyTorch CUDA availability and perform smoke test.
- `check_faiss` (function): summary=yes, params=ok, examples=no — Check FAISS GPU availability and perform smoke test.
- `main` (function): summary=yes, params=ok, examples=no — Run GPU diagnostics and print results.

## Tags

low-coverage
