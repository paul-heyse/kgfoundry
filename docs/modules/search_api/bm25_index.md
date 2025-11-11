# search_api.bm25_index

FastAPI service exposing search endpoints, aggregation helpers, and Problem Details responses.

[View source on GitHub](https://github.com/paul-heyse/kgfoundry/blob/main/src/search_api/bm25_index.py)

## Hierarchy

- **Parent:** [search_api](../search_api.md)

## Sections

- **Public API**

## Contents

### search_api.bm25_index.BM25Doc

::: search_api.bm25_index.BM25Doc

### search_api.bm25_index.BM25Index

::: search_api.bm25_index.BM25Index

### search_api.bm25_index._as_str

::: search_api.bm25_index._as_str

### search_api.bm25_index._duckdb_module

::: search_api.bm25_index._duckdb_module

### search_api.bm25_index._validate_parquet_path

::: search_api.bm25_index._validate_parquet_path

### search_api.bm25_index.toks

::: search_api.bm25_index.toks

## Relationships

**Imports:** `__future__.annotations`, `collections.abc.Iterable`, `dataclasses.dataclass`, `functools.lru_cache`, `kgfoundry_common.errors.ConfigurationError`, `kgfoundry_common.errors.DeserializationError`, `kgfoundry_common.navmap_loader.load_nav_metadata`, `kgfoundry_common.problem_details.JsonValue`, `kgfoundry_common.safe_pickle_v2.UnsafeSerializationError`, `kgfoundry_common.safe_pickle_v2.load_unsigned_legacy`, `kgfoundry_common.serialization.deserialize_json`, `kgfoundry_common.serialization.serialize_json`, `kgfoundry_common.typing.gate_import`, `math`, `os`, `pathlib.Path`, `re`, `registry.duckdb_helpers.fetch_all`, `registry.duckdb_helpers.fetch_one`, `types.ModuleType`, `typing.TYPE_CHECKING`, `typing.cast`

**Imported by:** [search_api](../search_api.md)

## Autorefs Examples

- [search_api.bm25_index.BM25Doc][]
- [search_api.bm25_index.BM25Index][]
- [search_api.bm25_index._as_str][]
- [search_api.bm25_index._duckdb_module][]
- [search_api.bm25_index._validate_parquet_path][]

## Inheritance

```mermaid
classDiagram
    class BM25Doc
    class BM25Index
```

## Neighborhood

```d2
direction: right
"search_api.bm25_index": "search_api.bm25_index" { link: "https://github.com/paul-heyse/kgfoundry/blob/main/src/search_api/bm25_index.py" }
"__future__.annotations": "__future__.annotations"
"search_api.bm25_index" -> "__future__.annotations"
"collections.abc.Iterable": "collections.abc.Iterable"
"search_api.bm25_index" -> "collections.abc.Iterable"
"dataclasses.dataclass": "dataclasses.dataclass"
"search_api.bm25_index" -> "dataclasses.dataclass"
"functools.lru_cache": "functools.lru_cache"
"search_api.bm25_index" -> "functools.lru_cache"
"kgfoundry_common.errors.ConfigurationError": "kgfoundry_common.errors.ConfigurationError"
"search_api.bm25_index" -> "kgfoundry_common.errors.ConfigurationError"
"kgfoundry_common.errors.DeserializationError": "kgfoundry_common.errors.DeserializationError"
"search_api.bm25_index" -> "kgfoundry_common.errors.DeserializationError"
"kgfoundry_common.navmap_loader.load_nav_metadata": "kgfoundry_common.navmap_loader.load_nav_metadata"
"search_api.bm25_index" -> "kgfoundry_common.navmap_loader.load_nav_metadata"
"kgfoundry_common.problem_details.JsonValue": "kgfoundry_common.problem_details.JsonValue"
"search_api.bm25_index" -> "kgfoundry_common.problem_details.JsonValue"
"kgfoundry_common.safe_pickle_v2.UnsafeSerializationError": "kgfoundry_common.safe_pickle_v2.UnsafeSerializationError"
"search_api.bm25_index" -> "kgfoundry_common.safe_pickle_v2.UnsafeSerializationError"
"kgfoundry_common.safe_pickle_v2.load_unsigned_legacy": "kgfoundry_common.safe_pickle_v2.load_unsigned_legacy"
"search_api.bm25_index" -> "kgfoundry_common.safe_pickle_v2.load_unsigned_legacy"
"kgfoundry_common.serialization.deserialize_json": "kgfoundry_common.serialization.deserialize_json"
"search_api.bm25_index" -> "kgfoundry_common.serialization.deserialize_json"
"kgfoundry_common.serialization.serialize_json": "kgfoundry_common.serialization.serialize_json"
"search_api.bm25_index" -> "kgfoundry_common.serialization.serialize_json"
"kgfoundry_common.typing.gate_import": "kgfoundry_common.typing.gate_import"
"search_api.bm25_index" -> "kgfoundry_common.typing.gate_import"
"math": "math"
"search_api.bm25_index" -> "math"
"os": "os"
"search_api.bm25_index" -> "os"
"pathlib.Path": "pathlib.Path"
"search_api.bm25_index" -> "pathlib.Path"
"re": "re"
"search_api.bm25_index" -> "re"
"registry.duckdb_helpers.fetch_all": "registry.duckdb_helpers.fetch_all"
"search_api.bm25_index" -> "registry.duckdb_helpers.fetch_all"
"registry.duckdb_helpers.fetch_one": "registry.duckdb_helpers.fetch_one"
"search_api.bm25_index" -> "registry.duckdb_helpers.fetch_one"
"types.ModuleType": "types.ModuleType"
"search_api.bm25_index" -> "types.ModuleType"
"typing.TYPE_CHECKING": "typing.TYPE_CHECKING"
"search_api.bm25_index" -> "typing.TYPE_CHECKING"
"typing.cast": "typing.cast"
"search_api.bm25_index" -> "typing.cast"
"search_api": "search_api" { link: "https://github.com/paul-heyse/kgfoundry/blob/main/src/search_api/__init__.py" }
"search_api" -> "search_api.bm25_index"
"search_api" -> "search_api.bm25_index" { style: dashed }
```

