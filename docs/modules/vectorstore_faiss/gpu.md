# vectorstore_faiss.gpu

GPU-aware FAISS index helpers backed by the shared search API facade.

[View source on GitHub](https://github.com/paul-heyse/kgfoundry/blob/main/src/vectorstore_faiss/gpu.py)

## Hierarchy

- **Parent:** [vectorstore_faiss](../vectorstore_faiss.md)

## Sections

- **Public API**

## Contents

### vectorstore_faiss.gpu.FaissGpuIndex

::: vectorstore_faiss.gpu.FaissGpuIndex

### vectorstore_faiss.gpu._FaissGpuIndexState

::: vectorstore_faiss.gpu._FaissGpuIndexState

### vectorstore_faiss.gpu._get_gpu_state

::: vectorstore_faiss.gpu._get_gpu_state

### vectorstore_faiss.gpu._set_gpu_state

::: vectorstore_faiss.gpu._set_gpu_state

## Relationships

**Imports:** `__future__.annotations`, `collections.abc.Sequence`, `dataclasses.dataclass`, `kgfoundry_common.navmap_loader.load_nav_metadata`, `kgfoundry_common.numpy_typing.FloatMatrix`, `kgfoundry_common.numpy_typing.FloatVector`, `kgfoundry_common.numpy_typing.IntVector`, `kgfoundry_common.numpy_typing.normalize_l2`, `kgfoundry_common.typing.gate_import`, `logging`, `numpy`, `numpy.typing`, `search_api.faiss_gpu.GpuContext`, `search_api.faiss_gpu.clone_index_to_gpu`, `search_api.faiss_gpu.configure_search_parameters`, `search_api.faiss_gpu.detect_gpu_context`, `search_api.types.FaissIndexProtocol`, `search_api.types.FaissModuleProtocol`, `typing.TYPE_CHECKING`, `typing.cast`, `weakref.WeakKeyDictionary`

## Autorefs Examples

- [vectorstore_faiss.gpu.FaissGpuIndex][]
- [vectorstore_faiss.gpu._FaissGpuIndexState][]
- [vectorstore_faiss.gpu._get_gpu_state][]
- [vectorstore_faiss.gpu._set_gpu_state][]

## Inheritance

```mermaid
classDiagram
    class FaissGpuIndex
    class _FaissGpuIndexState
```

## Neighborhood

```d2
direction: right
"vectorstore_faiss.gpu": "vectorstore_faiss.gpu" { link: "https://github.com/paul-heyse/kgfoundry/blob/main/src/vectorstore_faiss/gpu.py" }
"__future__.annotations": "__future__.annotations"
"vectorstore_faiss.gpu" -> "__future__.annotations"
"collections.abc.Sequence": "collections.abc.Sequence"
"vectorstore_faiss.gpu" -> "collections.abc.Sequence"
"dataclasses.dataclass": "dataclasses.dataclass"
"vectorstore_faiss.gpu" -> "dataclasses.dataclass"
"kgfoundry_common.navmap_loader.load_nav_metadata": "kgfoundry_common.navmap_loader.load_nav_metadata"
"vectorstore_faiss.gpu" -> "kgfoundry_common.navmap_loader.load_nav_metadata"
"kgfoundry_common.numpy_typing.FloatMatrix": "kgfoundry_common.numpy_typing.FloatMatrix"
"vectorstore_faiss.gpu" -> "kgfoundry_common.numpy_typing.FloatMatrix"
"kgfoundry_common.numpy_typing.FloatVector": "kgfoundry_common.numpy_typing.FloatVector"
"vectorstore_faiss.gpu" -> "kgfoundry_common.numpy_typing.FloatVector"
"kgfoundry_common.numpy_typing.IntVector": "kgfoundry_common.numpy_typing.IntVector"
"vectorstore_faiss.gpu" -> "kgfoundry_common.numpy_typing.IntVector"
"kgfoundry_common.numpy_typing.normalize_l2": "kgfoundry_common.numpy_typing.normalize_l2"
"vectorstore_faiss.gpu" -> "kgfoundry_common.numpy_typing.normalize_l2"
"kgfoundry_common.typing.gate_import": "kgfoundry_common.typing.gate_import"
"vectorstore_faiss.gpu" -> "kgfoundry_common.typing.gate_import"
"logging": "logging"
"vectorstore_faiss.gpu" -> "logging"
"numpy": "numpy"
"vectorstore_faiss.gpu" -> "numpy"
"numpy.typing": "numpy.typing"
"vectorstore_faiss.gpu" -> "numpy.typing"
"search_api.faiss_gpu.GpuContext": "search_api.faiss_gpu.GpuContext"
"vectorstore_faiss.gpu" -> "search_api.faiss_gpu.GpuContext"
"search_api.faiss_gpu.clone_index_to_gpu": "search_api.faiss_gpu.clone_index_to_gpu"
"vectorstore_faiss.gpu" -> "search_api.faiss_gpu.clone_index_to_gpu"
"search_api.faiss_gpu.configure_search_parameters": "search_api.faiss_gpu.configure_search_parameters"
"vectorstore_faiss.gpu" -> "search_api.faiss_gpu.configure_search_parameters"
"search_api.faiss_gpu.detect_gpu_context": "search_api.faiss_gpu.detect_gpu_context"
"vectorstore_faiss.gpu" -> "search_api.faiss_gpu.detect_gpu_context"
"search_api.types.FaissIndexProtocol": "search_api.types.FaissIndexProtocol"
"vectorstore_faiss.gpu" -> "search_api.types.FaissIndexProtocol"
"search_api.types.FaissModuleProtocol": "search_api.types.FaissModuleProtocol"
"vectorstore_faiss.gpu" -> "search_api.types.FaissModuleProtocol"
"typing.TYPE_CHECKING": "typing.TYPE_CHECKING"
"vectorstore_faiss.gpu" -> "typing.TYPE_CHECKING"
"typing.cast": "typing.cast"
"vectorstore_faiss.gpu" -> "typing.cast"
"weakref.WeakKeyDictionary": "weakref.WeakKeyDictionary"
"vectorstore_faiss.gpu" -> "weakref.WeakKeyDictionary"
"vectorstore_faiss": "vectorstore_faiss" { link: "https://github.com/paul-heyse/kgfoundry/blob/main/src/vectorstore_faiss/__init__.py" }
"vectorstore_faiss" -> "vectorstore_faiss.gpu" { style: dashed }
```

