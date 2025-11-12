# enrich/libcst_bridge.py

## Docstring

```
LibCST-powered index utilities (imports, defs, exports, docstrings).
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Iterator, Sequence
- from **contextlib** import suppress
- from **dataclasses** import dataclass, field
- from **pathlib** import Path
- from **typing** import Any, cast
- from **(absolute)** import libcst
- from **libcst** import metadata
- from **libcst.helpers** import get_full_name_for_node
- from **docstring_parser** import parse

## Definitions

- variable: `parse_docstring` (line 21)
- class: `ImportEntry` (line 25)
- class: `DefEntry` (line 36)
- class: `ModuleIndex` (line 45)
- function: `_extract_module_docstring` (line 82)
- function: `_literal_string_values` (line 112)
- function: `_extract_def_docstring` (line 150)
- function: `_summarize_docstring` (line 167)
- function: `_analyze_docstring` (line 179)
- function: `_iter_params` (line 205)
- function: `_exception_name` (line 220)
- function: `_infer_side_effects` (line 250)
- class: `_IndexVisitor` (line 272)
- function: `index_module` (line 561)
- function: `_lineno` (line 608)

## Graph Metrics

- **fan_in**: 4
- **fan_out**: 1
- **cycle_group**: 2

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 9
- recent churn 90: 9

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: LibCST-powered index utilities (imports, defs, exports, docstrings).
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

## Config References

- enrich/tagging_rules.yaml
- enrich/README.md

## Hotspot

- score: 2.72

## Side Effects

- filesystem
- network
- subprocess

## Complexity

- branches: 128
- cyclomatic: 129
- loc: 629

## Doc Coverage

- `ImportEntry` (class): summary=yes, examples=no — Normalized metadata for a single import statement.
- `DefEntry` (class): summary=yes, examples=no — Top-level function/class definition summary.
- `ModuleIndex` (class): summary=yes, examples=no — Aggregate module metadata returned by :func:`index_module`.
- `_extract_module_docstring` (function): summary=yes, params=ok, examples=no — Return the module docstring if present.
- `_literal_string_values` (function): summary=yes, params=ok, examples=no — Yield literal string values from constant containers.
- `_extract_def_docstring` (function): summary=no, examples=no
- `_summarize_docstring` (function): summary=no, examples=no
- `_analyze_docstring` (function): summary=no, examples=no
- `_iter_params` (function): summary=no, examples=no
- `_exception_name` (function): summary=yes, params=ok, examples=no — Extract exception name from LibCST expression node.

## Tags

low-coverage
