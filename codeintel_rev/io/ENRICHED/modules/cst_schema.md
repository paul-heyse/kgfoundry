# cst_build/cst_schema.py

## Docstring

```
Dataclasses and helpers describing the CST dataset schema.
```

## Imports

- from **__future__** import annotations
- from **dataclasses** import asdict, dataclass, field
- from **typing** import TypedDict

## Definitions

- variable: `SCHEMA_VERSION` (line 9)
- class: `DocSnippet` (line 12)
- class: `ImportMetadata` (line 19)
- class: `StitchCandidate` (line 29)
- class: `Span` (line 38)
- class: `StitchInfo` (line 61)
- class: `NodeRecord` (line 92)
- class: `CollectorStats` (line 147)
- function: `_format_doc` (line 198)
- function: `_assign_optional` (line 209)

## Graph Metrics

- **fan_in**: 5
- **fan_out**: 1
- **cycle_group**: 107

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

- **summary**: Dataclasses and helpers describing the CST dataset schema.
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

- score: 2.12

## Side Effects

- none detected

## Complexity

- branches: 12
- cyclomatic: 13
- loc: 221

## Doc Coverage

- `DocSnippet` (class): summary=yes, examples=no — Short docstring snippets recorded on nodes.
- `ImportMetadata` (class): summary=yes, examples=no — Normalized import metadata for Import/ImportFrom nodes.
- `StitchCandidate` (class): summary=yes, examples=no — Debug candidate entry for stitching heuristics.
- `Span` (class): summary=yes, examples=no — Source span tracked for each node.
- `StitchInfo` (class): summary=yes, examples=no — Join metadata linking nodes to module records and SCIP symbols.
- `NodeRecord` (class): summary=yes, examples=no — Single CST node row ready for serialization.
- `CollectorStats` (class): summary=yes, examples=no — Aggregated counters for provider usage.
- `_format_doc` (function): summary=no, examples=no
- `_assign_optional` (function): summary=no, examples=no

## Tags

low-coverage
