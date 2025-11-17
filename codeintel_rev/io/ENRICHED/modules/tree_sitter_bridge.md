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
- from **collections.abc** import Iterator, Sequence
- from **contextlib** import contextmanager
- from **dataclasses** import dataclass, field, replace
- from **pathlib** import Path
- from **typing** import Any, Protocol, cast
- from **tree_sitter** import Language, Node, Parser, Query, Tree
- from **tree_sitter_python** import language

## Definitions

- variable: `LOGGER` (line 18)
- class: `OutlineConfig` (line 42)
- function: `override_outline_config` (line 52)
- class: `QueryProtocol` (line 62)
- function: `_as_language` (line 69)
- function: `_lang_for_ext` (line 91)
- class: `OutlineNode` (line 129)
- class: `TSOutline` (line 139)
- function: `build_outline` (line 146)
- function: `_set_parser_language` (line 182)
- function: `_extract_identifier` (line 191)
- function: `_outline_with_query` (line 217)
- function: `_outline_with_dfs` (line 253)
- function: `_get_outline_query` (line 275)
- function: `_node_text` (line 292)

## Graph Metrics

- **fan_in**: 1
- **fan_out**: 1
- **cycle_group**: 73

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 7
- recent churn 90: 7

## Usage

- used by files: 0
- used by symbols: 0

## Doc Health

- **summary**: Tree-sitter outline helpers used for enrichment artifacts.
- has summary: yes
- param parity: no
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

- score: 2.07

## Side Effects

- filesystem

## Complexity

- branches: 35
- cyclomatic: 36
- loc: 296

## Doc Coverage

- `OutlineConfig` (class): summary=yes, examples=no — Configuration toggles for outline generation.
- `override_outline_config` (function): summary=yes, params=mismatch, examples=no — Temporarily override outline configuration flags.
- `QueryProtocol` (class): summary=yes, examples=no — Subset of :class:`tree_sitter.Query` APIs required for outlines.
- `_as_language` (function): summary=yes, params=mismatch, examples=no — Return a ``Language`` instance for ``candidate`` when possible.
- `_lang_for_ext` (function): summary=yes, params=ok, examples=no — Resolve a Tree-sitter language for ``ext``.
- `OutlineNode` (class): summary=yes, examples=no — Serializable view of a function/class definition.
- `TSOutline` (class): summary=yes, examples=no — Bundle of outline nodes plus the originating Tree-sitter language.
- `build_outline` (function): summary=yes, params=ok, examples=no — Produce a best-effort outline for ``path``'s contents.
- `_set_parser_language` (function): summary=yes, params=mismatch, examples=no — Bind ``parser`` to ``language`` across Tree-sitter releases.
- `_extract_identifier` (function): summary=yes, params=ok, examples=no — Return the identifier name for ``node`` if available.

## Tags

low-coverage
