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
- from **typing** import Any, ClassVar, Protocol, cast
- from **(absolute)** import libcst
- from **libcst** import metadata
- from **libcst.helpers** import get_full_name_for_node
- from **docstring_parser** import parse

## Definitions

- variable: `parse_docstring` (line 21)
- class: `NodeHandler` (line 24)
- class: `ImportEntry` (line 33)
- class: `DefEntry` (line 44)
- class: `ModuleIndex` (line 53)
- function: `_extract_module_docstring` (line 90)
- function: `_literal_string_values` (line 120)
- function: `_extract_def_docstring` (line 158)
- function: `_summarize_docstring` (line 175)
- function: `_analyze_docstring` (line 187)
- function: `_iter_params` (line 213)
- function: `_exception_name` (line 228)
- function: `_infer_side_effects` (line 258)
- class: `_IndexVisitor` (line 307)
- function: `index_module` (line 718)
- function: `_lineno` (line 765)

## Graph Metrics

- **fan_in**: 4
- **fan_out**: 1
- **cycle_group**: 2

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 11
- recent churn 90: 11

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
- enrich/PLAYBOOK.md
- enrich/README.md

## Hotspot

- score: 2.70

## Side Effects

- filesystem
- network
- subprocess

## Complexity

- branches: 117
- cyclomatic: 118
- loc: 786

## Doc Coverage

- `NodeHandler` (class): summary=yes, examples=no — Callable signature for node-dispatch handlers.
- `ImportEntry` (class): summary=yes, examples=no — Normalized metadata for a single import statement.
- `DefEntry` (class): summary=yes, examples=no — Top-level function/class definition summary.
- `ModuleIndex` (class): summary=yes, examples=no — Aggregate module metadata returned by :func:`index_module`.
- `_extract_module_docstring` (function): summary=yes, params=ok, examples=no — Return the module docstring if present.
- `_literal_string_values` (function): summary=yes, params=ok, examples=no — Yield literal string values from constant containers.
- `_extract_def_docstring` (function): summary=no, examples=no
- `_summarize_docstring` (function): summary=no, examples=no
- `_analyze_docstring` (function): summary=no, examples=no
- `_iter_params` (function): summary=no, examples=no

## Tags

low-coverage
