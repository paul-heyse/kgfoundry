# typing.py

## Docstring

```
Typing façade for codeintel_rev heavy optional dependencies.

This module centralizes numpy-style array aliases and exposes a wrapper around
``kgfoundry_common.typing.gate_import`` that is aware of the local heavy
dependency policy. Keeping aliases and dependency metadata in one place lets
lint/type tooling (PR-E) and runtime helpers share the same source of truth.
```

## Imports

- from **__future__** import annotations
- from **typing** import TYPE_CHECKING, Any, Protocol
- from **kgfoundry_common.typing** import HEAVY_DEPS
- from **kgfoundry_common.typing** import gate_import
- from **(absolute)** import numpy
- from **(absolute)** import numpy.typing

## Definitions

- variable: `NDArrayF32` (line 24)
- variable: `NDArrayI64` (line 25)
- variable: `NDArrayAny` (line 26)
- variable: `HEAVY_DEPS` (line 40)
- function: `gate_import` (line 44)
- class: `TorchDeviceProperties` (line 87)
- class: `TorchCudaAPI` (line 93)
- class: `TorchTensor` (line 113)
- class: `TorchModule` (line 126)
- class: `FaissStandardGpuResources` (line 144)
- class: `FaissGpuClonerOptions` (line 149)
- class: `FaissIndex` (line 157)
- class: `FaissGpuIndexFlatIP` (line 163)
- class: `FaissModule` (line 175)
- class: `NumpyRandomState` (line 208)
- class: `NumpyRandomNamespace` (line 214)
- class: `NumpyLinalgNamespace` (line 220)
- class: `NumpyModule` (line 226)

## Dependency Graph

- **fan_in**: 68
- **fan_out**: 0
- **cycle_group**: 0

## Declared Exports (__all__)

FaissModule, HEAVY_DEPS, NDArrayAny, NDArrayF32, NDArrayI64, NumpyModule, TorchModule, gate_import

## Doc Metrics

- **summary**: Typing façade for codeintel_rev heavy optional dependencies.
- has summary: yes
- param parity: yes
- examples present: no

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Side Effects

- none detected

## Complexity

- branches: 1
- cyclomatic: 2
- loc: 231

## Doc Coverage

- `gate_import` (function): summary=yes, params=ok, examples=no — Resolve ``module_name`` lazily using the heavy dependency policy.
- `TorchDeviceProperties` (class): summary=yes, examples=no — Subset of torch.cuda device properties accessed by diagnostics.
- `TorchCudaAPI` (class): summary=yes, examples=no — Minimal CUDA API surface used throughout the codebase.
- `TorchTensor` (class): summary=yes, examples=no — Tensor operations invoked inside diagnostics.
- `TorchModule` (class): summary=yes, examples=no — Subset of torch's module-level API we rely on.
- `FaissStandardGpuResources` (class): summary=yes, examples=no — GPU resource handle for FAISS.
- `FaissGpuClonerOptions` (class): summary=yes, examples=no — Options controlling FAISS GPU cloning behavior.
- `FaissIndex` (class): summary=yes, examples=no — Minimal FAISS index surface used in diagnostics.
- `FaissGpuIndexFlatIP` (class): summary=yes, examples=no — GPU FAISS index used for smoke testing.
- `FaissModule` (class): summary=yes, examples=no — Subset of the FAISS module accessed via gate_import.

## Tags

public-api
