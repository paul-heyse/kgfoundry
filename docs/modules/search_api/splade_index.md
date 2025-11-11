# search_api.splade_index

FastAPI service exposing search endpoints, aggregation helpers, and Problem Details responses.

[View source on GitHub](https://github.com/paul-heyse/kgfoundry/blob/main/src/search_api/splade_index.py)

## Hierarchy

- **Parent:** [search_api](../search_api.md)

## Sections

- **Public API**

## Contents

### search_api.splade_index.SpladeDoc

::: search_api.splade_index.SpladeDoc

### search_api.splade_index.SpladeIndex

::: search_api.splade_index.SpladeIndex

### search_api.splade_index._duckdb_module

::: search_api.splade_index._duckdb_module

### search_api.splade_index.tok

::: search_api.splade_index.tok

## Relationships

**Imports:** `__future__.annotations`, `collections.abc.Sequence`, `dataclasses.dataclass`, `duckdb.DuckDBPyConnection`, `functools.lru_cache`, `kgfoundry_common.navmap_loader.load_nav_metadata`, `kgfoundry_common.typing.gate_import`, `pathlib.Path`, `re`, `types.ModuleType`, `typing.Final`, `typing.TYPE_CHECKING`, `typing.cast`

**Imported by:** [search_api](../search_api.md)

## Autorefs Examples

- [search_api.splade_index.SpladeDoc][]
- [search_api.splade_index.SpladeIndex][]
- [search_api.splade_index._duckdb_module][]
- [search_api.splade_index.tok][]

## Inheritance

```mermaid
classDiagram
    class SpladeDoc
    class SpladeIndex
```

## Neighborhood

```d2
direction: right
"search_api.splade_index": "search_api.splade_index" { link: "https://github.com/paul-heyse/kgfoundry/blob/main/src/search_api/splade_index.py" }
"__future__.annotations": "__future__.annotations"
"search_api.splade_index" -> "__future__.annotations"
"collections.abc.Sequence": "collections.abc.Sequence"
"search_api.splade_index" -> "collections.abc.Sequence"
"dataclasses.dataclass": "dataclasses.dataclass"
"search_api.splade_index" -> "dataclasses.dataclass"
"duckdb.DuckDBPyConnection": "duckdb.DuckDBPyConnection"
"search_api.splade_index" -> "duckdb.DuckDBPyConnection"
"functools.lru_cache": "functools.lru_cache"
"search_api.splade_index" -> "functools.lru_cache"
"kgfoundry_common.navmap_loader.load_nav_metadata": "kgfoundry_common.navmap_loader.load_nav_metadata"
"search_api.splade_index" -> "kgfoundry_common.navmap_loader.load_nav_metadata"
"kgfoundry_common.typing.gate_import": "kgfoundry_common.typing.gate_import"
"search_api.splade_index" -> "kgfoundry_common.typing.gate_import"
"pathlib.Path": "pathlib.Path"
"search_api.splade_index" -> "pathlib.Path"
"re": "re"
"search_api.splade_index" -> "re"
"types.ModuleType": "types.ModuleType"
"search_api.splade_index" -> "types.ModuleType"
"typing.Final": "typing.Final"
"search_api.splade_index" -> "typing.Final"
"typing.TYPE_CHECKING": "typing.TYPE_CHECKING"
"search_api.splade_index" -> "typing.TYPE_CHECKING"
"typing.cast": "typing.cast"
"search_api.splade_index" -> "typing.cast"
"search_api": "search_api" { link: "https://github.com/paul-heyse/kgfoundry/blob/main/src/search_api/__init__.py" }
"search_api" -> "search_api.splade_index"
"search_api" -> "search_api.splade_index" { style: dashed }
```

