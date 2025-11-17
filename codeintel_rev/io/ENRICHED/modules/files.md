# mcp_server/adapters/files.py

## Docstring

```
File and scope management adapter.

Provides file listing, reading, and scope configuration.
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import asyncio
- from **(absolute)** import fnmatch
- from **(absolute)** import os
- from **collections.abc** import Sequence
- from **dataclasses** import dataclass
- from **pathlib** import Path
- from **typing** import TYPE_CHECKING, cast
- from **codeintel_rev.app.middleware** import get_session_id
- from **codeintel_rev.errors** import FileReadError, InvalidLineRangeError, PathNotDirectoryError, PathNotFoundError
- from **codeintel_rev.io.path_utils** import PathOutsideRepositoryError, resolve_within_repo
- from **codeintel_rev.mcp_server.schemas** import ScopeIn
- from **codeintel_rev.mcp_server.scope_utils** import LANGUAGE_EXTENSIONS, get_effective_scope, merge_scope_filters
- from **codeintel_rev.app.config_context** import ApplicationContext

## Definitions

- class: `FileListFilters` (line 36)
- class: `DirectoryFilters` (line 46)
- function: `set_scope` (line 55)
- function: `list_paths` (line 94)
- function: `_normalize_list_paths_arguments` (line 190)
- function: `_list_paths_sync` (line 219)
- function: `_collect_filtered_paths` (line 319)
- function: `_prune_directories` (line 384)
- function: `_create_file_entry` (line 406)
- function: `open_file` (line 463)
- function: `_resolve_search_root` (line 569)
- function: `_matches_any` (line 616)
- function: `_relative_path_str` (line 621)
- function: `_safe_stat` (line 633)
- function: `_collect_language_extensions` (line 640)
- function: `_matches_language` (line 659)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 7
- **cycle_group**: 117

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 25
- recent churn 90: 25

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

list_paths, open_file, set_scope

## Doc Health

- **summary**: File and scope management adapter.
- has summary: yes
- param parity: no
- examples present: yes

## Typedness

- params annotated: 1.00
- returns annotated: 1.00
- untyped defs: 0
- type errors: 0

## Coverage

- lines covered: 0.00%
- defs covered: 0.00%

## Hotspot

- score: 2.56

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 49
- cyclomatic: 50
- loc: 677

## Doc Coverage

- `FileListFilters` (class): summary=yes, examples=no — Configuration for file listing filters.
- `DirectoryFilters` (class): summary=yes, examples=no — Prepared filters used during directory traversal.
- `set_scope` (function): summary=yes, params=ok, examples=yes — Set query scope for subsequent operations.
- `list_paths` (function): summary=yes, params=mismatch, examples=yes — List files in repository (async with threadpool offload).
- `_normalize_list_paths_arguments` (function): summary=no, examples=no
- `_list_paths_sync` (function): summary=yes, params=ok, examples=no — List files in repository (synchronous implementation).
- `_collect_filtered_paths` (function): summary=yes, params=ok, examples=no — Walk directories and apply include/exclude filters.
- `_prune_directories` (function): summary=no, examples=no
- `_create_file_entry` (function): summary=yes, params=ok, examples=no — Return a file entry dict when filters accept the file.
- `open_file` (function): summary=yes, params=ok, examples=yes — Read file content with optional line slicing.

## Tags

low-coverage, public-api
