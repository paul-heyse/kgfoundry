# enrich/tree_sitter_bridge.py

## Docstring

```
Tree-sitter outline helpers used for enrichment artifacts.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import importlib
- from **(absolute)** import importlib.util
- from **(absolute)** import logging
- from **(absolute)** import os
- from **collections.abc** import Sequence
- from **dataclasses** import dataclass, field
- from **pathlib** import Path
- from **typing** import Any, Protocol, cast
- from **tree_sitter** import Language, Node, Parser, Query, Tree
- from **tree_sitter_python** import language

## Definitions

- variable: `LOGGER` (line 30)
- class: `ParserProtocol` (line 41)
- class: `QueryProtocol` (line 53)
- function: `_lang_for_ext` (line 61)
- class: `OutlineNode` (line 99)
- class: `TSOutline` (line 109)
- function: `build_outline` (line 116)
- function: `_extract_identifier` (line 151)
- function: `_outline_with_query` (line 177)
- function: `_outline_with_dfs` (line 213)
- function: `_get_outline_query` (line 235)
- function: `_node_text` (line 252)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 87

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 6
- recent churn 90: 6

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

- score: 2.03

## Side Effects

- filesystem

## Complexity

- branches: 30
- cyclomatic: 31
- loc: 256

## Doc Coverage

- `ParserProtocol` (class): summary=yes, examples=no — Subset of :class:`tree_sitter.Parser` used by this module.
- `QueryProtocol` (class): summary=yes, examples=no — Subset of :class:`tree_sitter.Query` APIs required for outlines.
- `_lang_for_ext` (function): summary=yes, params=ok, examples=no — Resolve a Tree-sitter language for ``ext``.
- `OutlineNode` (class): summary=yes, examples=no — Serializable view of a function/class definition.
- `TSOutline` (class): summary=yes, examples=no — Bundle of outline nodes plus the originating Tree-sitter language.
- `build_outline` (function): summary=yes, params=ok, examples=no — Produce a best-effort outline for ``path``'s contents.
- `_extract_identifier` (function): summary=yes, params=ok, examples=no — Return the identifier name for ``node`` if available.
- `_outline_with_query` (function): summary=no, examples=no
- `_outline_with_dfs` (function): summary=no, examples=no
- `_get_outline_query` (function): summary=no, examples=no

## Tags

low-coverage
