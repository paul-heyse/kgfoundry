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
- from **typing** import TYPE_CHECKING, SupportsIndex, cast
- from **codeintel_rev.app.middleware** import get_session_id
- from **codeintel_rev.errors** import FileReadError, InvalidLineRangeError, PathNotDirectoryError, PathNotFoundError
- from **codeintel_rev.io.path_utils** import PathOutsideRepositoryError, resolve_within_repo
- from **codeintel_rev.mcp_server.schemas** import ScopeIn
- from **codeintel_rev.mcp_server.scope_utils** import LANGUAGE_EXTENSIONS, get_effective_scope, merge_scope_filters
- from **codeintel_rev.observability.execution_ledger** import record
- from **codeintel_rev.observability.execution_ledger** import step
- from **kgfoundry_common.logging** import get_logger
- from **codeintel_rev.app.config_context** import ApplicationContext

## Definitions

- variable: `LOGGER` (line 41)
- class: `FileListFilters` (line 45)
- class: `DirectoryFilters` (line 55)
- function: `set_scope` (line 64)
- function: `list_paths` (line 114)
- function: `_normalize_list_paths_arguments` (line 244)
- function: `_list_paths_sync` (line 276)
- function: `_collect_filtered_paths` (line 395)
- function: `_prune_directories` (line 460)
- function: `_create_file_entry` (line 482)
- function: `open_file` (line 539)
- function: `_resolve_search_root` (line 658)
- function: `_matches_any` (line 705)
- function: `_relative_path_str` (line 710)
- function: `_safe_stat` (line 722)
- function: `_collect_language_extensions` (line 729)
- function: `_matches_language` (line 748)

## Graph Metrics

- **fan_in**: 0
- **fan_out**: 8
- **cycle_group**: 137

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 20
- recent churn 90: 20

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

- score: 2.63

## Side Effects

- filesystem
- subprocess

## Complexity

- branches: 54
- cyclomatic: 55
- loc: 766

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
