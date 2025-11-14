# indexing/scip_reader.py

## Docstring

```
SCIP index reader for extracting symbol definitions and ranges.

Parses index.scip (protobuf) or index.scip.json and extracts symbol definitions
with precise ranges for chunking and code intelligence.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import json
- from **collections.abc** import Sequence
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING
- from **(absolute)** import msgspec
- from **collections.abc** import Iterable

## Definitions

- variable: `RANGE_TUPLE_LENGTH` (line 21)
- function: `_range_from_list` (line 24)
- function: `_parse_occurrence` (line 36)
- class: `Range` (line 66)
- class: `Occurrence` (line 101)
- class: `Document` (line 134)
- class: `SCIPIndex` (line 166)
- class: `SymbolDef` (line 189)
- function: `parse_scip_json` (line 225)
- function: `extract_definitions` (line 289)
- function: `get_top_level_definitions` (line 339)

## Graph Metrics

- **fan_in**: 2
- **fan_out**: 1
- **cycle_group**: 31

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 6
- recent churn 90: 6

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

Document, Occurrence, Range, SCIPIndex, SymbolDef, extract_definitions, get_top_level_definitions, parse_scip_json

## Doc Health

- **summary**: SCIP index reader for extracting symbol definitions and ranges.
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

- score: 2.17

## Side Effects

- filesystem

## Complexity

- branches: 33
- cyclomatic: 34
- loc: 422

## Doc Coverage

- `_range_from_list` (function): summary=no, examples=no
- `_parse_occurrence` (function): summary=no, examples=no
- `Range` (class): summary=yes, examples=no — Source code range with line and character positions.
- `Occurrence` (class): summary=yes, examples=no — Symbol occurrence in source code.
- `Document` (class): summary=yes, examples=no — SCIP document representing a source file.
- `SCIPIndex` (class): summary=yes, examples=no — SCIP index containing all indexed documents.
- `SymbolDef` (class): summary=yes, examples=no — Extracted symbol definition with location information.
- `parse_scip_json` (function): summary=yes, params=ok, examples=no — Parse SCIP index from JSON export.
- `extract_definitions` (function): summary=yes, params=ok, examples=no — Extract symbol definitions from SCIP index.
- `get_top_level_definitions` (function): summary=yes, params=ok, examples=no — Filter to top-level definitions (not nested inside others).

## Tags

low-coverage, public-api
