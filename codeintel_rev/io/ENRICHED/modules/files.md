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
- from **kgfoundry_common.logging** import get_logger
- from **codeintel_rev.app.config_context** import ApplicationContext

## Definitions

- variable: `LOGGER` (line 35)
- class: `FileListFilters` (line 39)
- class: `DirectoryFilters` (line 49)
- function: `set_scope` (line 58)
- function: `list_paths` (line 102)
- function: `_normalize_list_paths_arguments` (line 203)
- function: `_list_paths_sync` (line 235)
- function: `_collect_filtered_paths` (line 354)
- function: `_prune_directories` (line 419)
- function: `_create_file_entry` (line 441)
- function: `open_file` (line 498)
- function: `_resolve_search_root` (line 607)
- function: `_matches_any` (line 654)
- function: `_relative_path_str` (line 659)
- function: `_safe_stat` (line 671)
- function: `_collect_language_extensions` (line 678)
- function: `_matches_language` (line 697)

## Dependency Graph

- **fan_in**: 0
- **fan_out**: 7
- **cycle_group**: 90

## Declared Exports (__all__)

list_paths, open_file, set_scope

## Tags

public-api
