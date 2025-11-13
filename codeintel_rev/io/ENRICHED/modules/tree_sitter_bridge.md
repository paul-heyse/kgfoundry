# enrich/tree_sitter_bridge.py

## Docstring

```
Tree-sitter outline helpers used for enrichment artifacts.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import importlib
- from **(absolute)** import importlib.util
- from **dataclasses** import dataclass, field
- from **pathlib** import Path
- from **typing** import Any
- from **tree_sitter** import Language, Node, Parser
- from **tree_sitter_python** import language

## Definitions

- function: `_lang_for_ext` (line 27)
- class: `OutlineNode` (line 65)
- class: `TSOutline` (line 75)
- function: `build_outline` (line 82)
- function: `_extract_identifier` (line 133)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 19

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

- **summary**: Tree-sitter outline helpers used for enrichment artifacts.
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

- score: 1.87

## Side Effects

- filesystem

## Complexity

- branches: 17
- cyclomatic: 18
- loc: 157

## Doc Coverage

- `_lang_for_ext` (function): summary=yes, params=ok, examples=no — Resolve a Tree-sitter language for ``ext``.
- `OutlineNode` (class): summary=yes, examples=no — Serializable view of a function/class definition.
- `TSOutline` (class): summary=yes, examples=no — Bundle of outline nodes plus the originating Tree-sitter language.
- `build_outline` (function): summary=yes, params=ok, examples=no — Produce a best-effort outline for ``path``'s contents.
- `_extract_identifier` (function): summary=yes, params=ok, examples=no — Return the identifier name for ``node`` if available.

## Tags

low-coverage
