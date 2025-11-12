# cli_enrich.py

## Docstring

```
CLI entrypoint for repo enrichment and overlay generation.
```

## Imports

- from **__future__** import annotations
- from **collections.abc** import Iterable, Mapping, Sequence
- from **dataclasses** import asdict, dataclass
- from **datetime** import UTC, datetime
- from **pathlib** import Path
- from **typing** import Any
- from **(absolute)** import typer
- from **codeintel_rev.enrich.libcst_bridge** import ImportEntry, index_module
- from **codeintel_rev.enrich.output_writers** import write_json, write_jsonl, write_markdown_module
- from **codeintel_rev.enrich.scip_reader** import Document, SCIPIndex
- from **codeintel_rev.enrich.stubs_overlay** import generate_overlay_for_file
- from **codeintel_rev.enrich.tagging** import ModuleTraits, infer_tags, load_rules
- from **codeintel_rev.enrich.tree_sitter_bridge** import build_outline
- from **codeintel_rev.enrich.type_integration** import TypeSummary, collect_pyrefly, collect_pyright
- from **(absolute)** import yaml

## Definitions

- class: `ModuleRecord` (line 50)
- class: `ScipContext` (line 67)
- class: `TypeSignals` (line 75)
- function: `_iter_files` (line 82)
- function: `_collect_imported_modules` (line 125)
- function: `_max_type_errors` (line 170)
- function: `_outline_nodes` (line 219)
- function: `_build_module_row` (line 272)
- function: `_write_tag_index` (line 391)
- function: `main` (line 406)

## Tags

cli, overlay-needed
