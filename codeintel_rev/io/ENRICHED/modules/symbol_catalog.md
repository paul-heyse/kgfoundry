# io/symbol_catalog.py

## Docstring

```
DuckDB symbol catalog writer.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Iterable, Sequence
- from **dataclasses** import dataclass
- from **codeintel_rev.io.duckdb_manager** import DuckDBManager

## Definitions

- class: `SymbolDefRow` (line 12)
- class: `SymbolOccurrenceRow` (line 30)
- class: `SymbolCatalog` (line 45)
- function: `__init__` (line 48)
- function: `ensure_schema` (line 51)
- function: `upsert_symbol_defs` (line 125)
- function: `bulk_insert_occurrences` (line 168)
- function: `bulk_insert_chunk_symbols` (line 176)
- function: `fetch_symbol_defs` (line 188)

## Tags

overlay-needed
