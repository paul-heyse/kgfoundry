# search_api.types

FastAPI service exposing search endpoints, aggregation helpers, and Problem Details responses.

[View source on GitHub](https://github.com/paul-heyse/kgfoundry/blob/main/src/search_api/types.py)

## Hierarchy

- **Parent:** [search_api](../search_api.md)

## Sections

- **Public API**

## Contents

### search_api.types.AgentSearchQuery

::: search_api.types.AgentSearchQuery

### search_api.types.AgentSearchResponse

::: search_api.types.AgentSearchResponse

*Bases:* TypedDict

### search_api.types.BM25IndexProtocol

::: search_api.types.BM25IndexProtocol

*Bases:* Protocol

### search_api.types.FaissIndexProtocol

::: search_api.types.FaissIndexProtocol

*Bases:* Protocol

### search_api.types.FaissModuleProtocol

::: search_api.types.FaissModuleProtocol

*Bases:* Protocol

### search_api.types.GpuClonerOptionsProtocol

::: search_api.types.GpuClonerOptionsProtocol

*Bases:* Protocol

### search_api.types.GpuResourcesProtocol

::: search_api.types.GpuResourcesProtocol

*Bases:* Protocol

### search_api.types.SpladeEncoderProtocol

::: search_api.types.SpladeEncoderProtocol

*Bases:* Protocol

### search_api.types.VectorSearchResult

::: search_api.types.VectorSearchResult

### search_api.types.VectorSearchResultTypedDict

::: search_api.types.VectorSearchResultTypedDict

*Bases:* TypedDict

### search_api.types._FaissModuleAdapter

::: search_api.types._FaissModuleAdapter

### search_api.types._LegacyFaissModule

::: search_api.types._LegacyFaissModule

*Bases:* Protocol

### search_api.types._labels_or_default

::: search_api.types._labels_or_default

### search_api.types._legacy_index_flat_ip

::: search_api.types._legacy_index_flat_ip

### search_api.types._legacy_index_id_map2

::: search_api.types._legacy_index_id_map2

### search_api.types._legacy_normalize_l2

::: search_api.types._legacy_normalize_l2

### search_api.types.wrap_faiss_module

::: search_api.types.wrap_faiss_module

## Relationships

**Imports:** `__future__.annotations`, `collections.abc.Callable`, `collections.abc.Mapping`, `collections.abc.Sequence`, `contextlib.suppress`, `dataclasses.dataclass`, `kgfoundry_common.navmap_loader.load_nav_metadata`, `kgfoundry_common.problem_details.JsonValue`, `kgfoundry_common.typing.gate_import`, `numpy`, `numpy.typing`, `numpy.typing.NDArray`, `operator.attrgetter`, `typing.Protocol`, `typing.TYPE_CHECKING`, `typing.TypedDict`, `typing.cast`

**Imported by:** [search_api](../search_api.md)

## Autorefs Examples

- [search_api.types.AgentSearchQuery][]
- [search_api.types.AgentSearchResponse][]
- [search_api.types.BM25IndexProtocol][]
- [search_api.types._labels_or_default][]
- [search_api.types._legacy_index_flat_ip][]
- [search_api.types._legacy_index_id_map2][]

## Inheritance

```mermaid
classDiagram
    class AgentSearchQuery
    class AgentSearchResponse
    class TypedDict
    TypedDict <|-- AgentSearchResponse
    class BM25IndexProtocol
    class Protocol
    Protocol <|-- BM25IndexProtocol
    class FaissIndexProtocol
    Protocol <|-- FaissIndexProtocol
    class FaissModuleProtocol
    Protocol <|-- FaissModuleProtocol
    class GpuClonerOptionsProtocol
    Protocol <|-- GpuClonerOptionsProtocol
    class GpuResourcesProtocol
    Protocol <|-- GpuResourcesProtocol
    class SpladeEncoderProtocol
    Protocol <|-- SpladeEncoderProtocol
    class VectorSearchResult
    class VectorSearchResultTypedDict
    TypedDict <|-- VectorSearchResultTypedDict
    class _FaissModuleAdapter
    class _LegacyFaissModule
    Protocol <|-- _LegacyFaissModule
```

## Neighborhood

```d2
direction: right
"search_api.types": "search_api.types" { link: "https://github.com/paul-heyse/kgfoundry/blob/main/src/search_api/types.py" }
"__future__.annotations": "__future__.annotations"
"search_api.types" -> "__future__.annotations"
"collections.abc.Callable": "collections.abc.Callable"
"search_api.types" -> "collections.abc.Callable"
"collections.abc.Mapping": "collections.abc.Mapping"
"search_api.types" -> "collections.abc.Mapping"
"collections.abc.Sequence": "collections.abc.Sequence"
"search_api.types" -> "collections.abc.Sequence"
"contextlib.suppress": "contextlib.suppress"
"search_api.types" -> "contextlib.suppress"
"dataclasses.dataclass": "dataclasses.dataclass"
"search_api.types" -> "dataclasses.dataclass"
"kgfoundry_common.navmap_loader.load_nav_metadata": "kgfoundry_common.navmap_loader.load_nav_metadata"
"search_api.types" -> "kgfoundry_common.navmap_loader.load_nav_metadata"
"kgfoundry_common.problem_details.JsonValue": "kgfoundry_common.problem_details.JsonValue"
"search_api.types" -> "kgfoundry_common.problem_details.JsonValue"
"kgfoundry_common.typing.gate_import": "kgfoundry_common.typing.gate_import"
"search_api.types" -> "kgfoundry_common.typing.gate_import"
"numpy": "numpy"
"search_api.types" -> "numpy"
"numpy.typing": "numpy.typing"
"search_api.types" -> "numpy.typing"
"numpy.typing.NDArray": "numpy.typing.NDArray"
"search_api.types" -> "numpy.typing.NDArray"
"operator.attrgetter": "operator.attrgetter"
"search_api.types" -> "operator.attrgetter"
"typing.Protocol": "typing.Protocol"
"search_api.types" -> "typing.Protocol"
"typing.TYPE_CHECKING": "typing.TYPE_CHECKING"
"search_api.types" -> "typing.TYPE_CHECKING"
"typing.TypedDict": "typing.TypedDict"
"search_api.types" -> "typing.TypedDict"
"typing.cast": "typing.cast"
"search_api.types" -> "typing.cast"
"search_api": "search_api" { link: "https://github.com/paul-heyse/kgfoundry/blob/main/src/search_api/__init__.py" }
"search_api" -> "search_api.types"
"search_api" -> "search_api.types" { style: dashed }
```

