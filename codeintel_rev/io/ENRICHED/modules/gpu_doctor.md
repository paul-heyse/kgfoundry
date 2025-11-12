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
- from **typing** import TYPE_CHECKING, cast
- from **codeintel_rev._lazy_imports** import LazyModule
- from **codeintel_rev.typing** import gate_import
- from **(absolute)** import faiss
- from **(absolute)** import numpy
- from **(absolute)** import torch

## Definitions

- function: `check_torch` (line 36)
- function: `check_faiss` (line 96)
- function: `main` (line 149)

## Tags

overlay-needed
