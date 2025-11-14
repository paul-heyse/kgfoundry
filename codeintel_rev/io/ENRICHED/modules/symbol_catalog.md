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

## Graph Metrics

- **fan_in**: 3
- **fan_out**: 1
- **cycle_group**: 42

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 4
- recent churn 90: 4

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: DuckDB symbol catalog writer.
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

- score: 1.94

## Side Effects

- none detected

## Complexity

- branches: 10
- cyclomatic: 11
- loc: 241

## Doc Coverage

- `SymbolDefRow` (class): summary=yes, examples=no — Immutable row describing a symbol definition.
- `SymbolOccurrenceRow` (class): summary=yes, examples=no — Service row for individual symbol occurrences.
- `SymbolCatalog` (class): summary=yes, examples=no — Writer for symbol metadata tables alongside `chunks`.

## Tags

low-coverage
