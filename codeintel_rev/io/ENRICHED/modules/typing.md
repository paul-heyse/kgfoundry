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
- from **collections.abc** import Callable, Mapping, Sequence
- from **os** import PathLike
- from **typing** import TYPE_CHECKING, Any, Literal, Protocol
- from **kgfoundry_common.typing** import HEAVY_DEPS
- from **kgfoundry_common.typing** import gate_import
- from **(absolute)** import numpy
- from **(absolute)** import numpy.typing

## Definitions

- variable: `NDArrayF32` (line 26)
- variable: `NDArrayI64` (line 27)
- variable: `NDArrayAny` (line 28)
- variable: `HEAVY_DEPS` (line 44)
- function: `gate_import` (line 48)
- class: `TorchDeviceProperties` (line 91)
- class: `TorchCudaAPI` (line 97)
- class: `TorchTensor` (line 194)
- class: `TorchModule` (line 243)
- class: `FaissStandardGpuResources` (line 261)
- class: `FaissGpuClonerOptions` (line 265)
- class: `FaissIndex` (line 273)
- class: `FaissGpuIndexFlatIP` (line 279)
- class: `FaissModule` (line 291)
- class: `NumpyRandomState` (line 330)
- class: `NumpyRandomNamespace` (line 351)
- class: `NumpyLinalgNamespace` (line 375)
- class: `NumpyModule` (line 400)
- class: `PolarsDataFrame` (line 407)
- class: `PolarsModule` (line 428)

## Graph Metrics

- **fan_in**: 108
- **fan_out**: 0
- **cycle_group**: 0

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 14
- recent churn 90: 14

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

FaissModule, HEAVY_DEPS, NDArrayAny, NDArrayF32, NDArrayI64, NumpyModule, PolarsDataFrame, PolarsModule, TorchModule, gate_import

## Doc Health

- **summary**: Typing façade for codeintel_rev heavy optional dependencies.
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

- score: 2.75

## Side Effects

- filesystem

## Complexity

- branches: 1
- cyclomatic: 2
- loc: 454

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

low-coverage, public-api, reexport-hub
