# mcp_server/retrieval/xtr_cli.py

## Docstring

```
Typer CLI for building, verifying, and probing XTR artifacts.
```

## Imports

- from **__future__** import annotations
- from **typing** import Annotated
- from **(absolute)** import typer
- from **codeintel_rev.app.config_context** import resolve_application_paths
- from **codeintel_rev.config.settings** import load_settings
- from **codeintel_rev.indexing.xtr_build** import build_xtr_index
- from **codeintel_rev.io.xtr_manager** import XTRIndex

## Definitions

- function: `build` (line 31)
- function: `verify` (line 44)
- function: `search` (line 70)
- function: `main` (line 158)

## Tags

cli, overlay-needed
