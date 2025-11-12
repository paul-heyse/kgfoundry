# errors.py

## Docstring

```
CodeIntel-specific exception hierarchy with Problem Details support.

This module defines domain-specific exceptions for CodeIntel MCP server operations.
All exceptions inherit from ``KgFoundryError`` and include automatic RFC 9457
Problem Details mapping with appropriate HTTP status codes and structured context.

The exception hierarchy is organized by operation category:

- **File Operations**: ``FileOperationError``, ``FileReadError``, ``InvalidLineRangeError``
- **Git Operations**: ``GitOperationError``
- **Search Operations**: Use ``VectorSearchError``, ``EmbeddingError`` from kgfoundry_common

Examples
--------
Raising file operation error:

>>> raise FileReadError("Binary file or encoding error", path="binary_file.png")

Raising invalid line range error with context:

>>> raise InvalidLineRangeError(
...     "start_line must be positive", path="src/main.py", line_range=(0, 10)
... )

Raising Git operation error:

>>> try:
...     git_client.blame_range(path, start, end)
... except git.exc.GitCommandError as exc:
...     raise GitOperationError("Git blame failed", path=path, git_command="blame") from exc
```

## Imports

- from **__future__** import annotations
- from **kgfoundry_common.errors** import ErrorCode, KgFoundryError

## Definitions

- class: `FileOperationError` (line 40)
- function: `__init__` (line 80)
- class: `FileReadError` (line 95)
- class: `InvalidLineRangeError` (line 142)
- function: `__init__` (line 192)
- class: `PathNotFoundError` (line 214)
- function: `__init__` (line 217)
- class: `PathNotDirectoryError` (line 233)
- function: `__init__` (line 236)
- class: `GitOperationError` (line 255)
- function: `__init__` (line 312)
- class: `RuntimeLifecycleError` (line 334)
- function: `__init__` (line 337)
- class: `RuntimeUnavailableError` (line 353)
- function: `__init__` (line 356)

## Tags

overlay-needed, public-api
