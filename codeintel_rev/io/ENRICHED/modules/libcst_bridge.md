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
- function: `_literal_string_values` (line 76)
- class: `_IndexVisitor` (line 108)
- function: `__init__` (line 113)
- function: `on_visit` (line 119)
- function: `_handle_import` (line 141)
- function: `_handle_import_from` (line 157)
- function: `_handle_function_def` (line 186)
- function: `_handle_class_def` (line 194)
- function: `_handle_assign` (line 202)
- function: `index_module` (line 208)

## Tags

overlay-needed
