# enrich/libcst_bridge.py

## Docstring

```
LibCST-powered index utilities (imports, defs, exports, docstrings).
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Iterator
- from **contextlib** import suppress
- from **dataclasses** import dataclass, field
- from **pathlib** import Path
- from **(absolute)** import libcst
- from **libcst** import metadata
- from **libcst.helpers** import get_full_name_for_node

## Definitions

- class: `ImportEntry` (line 19)
- class: `DefEntry` (line 30)
- class: `ModuleIndex` (line 39)
- function: `_extract_module_docstring` (line 51)
- function: `_literal_string_values` (line 81)
- class: `_IndexVisitor` (line 119)
- function: `index_module` (line 256)
- function: `_lineno` (line 294)

## Dependency Graph

- **fan_in**: 2
- **fan_out**: 0
- **cycle_group**: 3
