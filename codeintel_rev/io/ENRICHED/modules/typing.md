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
- from **(absolute)** import typing

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

- **fan_in**: 66
- **fan_out**: 0
- **cycle_group**: 0

## Declared Exports (__all__)

FaissModule, HEAVY_DEPS, NDArrayAny, NDArrayF32, NDArrayI64, NumpyModule, TorchModule, gate_import

## Tags

public-api
