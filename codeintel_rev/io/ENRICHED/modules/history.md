# mcp_server/adapters/history.py

## Docstring

```
Git history adapter for blame and log operations.

Provides git blame and commit history using GitPython via GitClient.
This replaces subprocess-based Git operations with typed Python APIs for
better performance (50-80ms latency reduction) and reliability.
```

## Imports

- from **__future__** import annotations
- from **typing** import TYPE_CHECKING
- from **(absolute)** import exc
- from **codeintel_rev.errors** import GitOperationError, PathNotFoundError
- from **codeintel_rev.io.path_utils** import resolve_within_repo
- from **kgfoundry_common.logging** import get_logger
- from **codeintel_rev.app.config_context** import ApplicationContext

## Definitions

- function: `blame_range` (line 24)
- function: `file_history` (line 119)

## Tags

overlay-needed, public-api
