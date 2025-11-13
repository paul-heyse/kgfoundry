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
- from **collections.abc** import Mapping
- from **kgfoundry_common.errors** import ErrorCode, KgFoundryError

## Definitions

- class: `FileOperationError` (line 42)
- class: `FileReadError` (line 97)
- class: `InvalidLineRangeError` (line 144)
- class: `PathNotFoundError` (line 216)
- class: `PathNotDirectoryError` (line 235)
- class: `GitOperationError` (line 257)
- class: `RuntimeLifecycleError` (line 336)
- class: `RuntimeUnavailableError` (line 355)
- class: `VectorIndexStateError` (line 378)
- class: `VectorIndexIncompatibleError` (line 400)
- class: `CatalogJoinError` (line 422)

## Graph Metrics

- **fan_in**: 13
- **fan_out**: 0
- **cycle_group**: 25

## Ownership

- owner: paul-heyse
- primary authors: paul-heyse
- bus factor: 1.00
- recent churn 30: 5
- recent churn 90: 5

## Usage

- used by files: 0
- used by symbols: 0

## Declared Exports (__all__)

FileOperationError, FileReadError, GitOperationError, InvalidLineRangeError, PathNotDirectoryError, PathNotFoundError, RuntimeLifecycleError, RuntimeUnavailableError

## Doc Health

- **summary**: CodeIntel-specific exception hierarchy with Problem Details support.
- has summary: yes
- param parity: yes
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

- score: 2.26

## Side Effects

- none detected

## Complexity

- branches: 7
- cyclomatic: 8
- loc: 467

## Doc Coverage

- `FileOperationError` (class): summary=yes, examples=yes — Base exception for file operation errors.
- `FileReadError` (class): summary=yes, examples=yes — Raised when file cannot be read due to encoding or binary content.
- `InvalidLineRangeError` (class): summary=yes, examples=yes — Raised when line range parameters are invalid.
- `PathNotFoundError` (class): summary=yes, examples=no — Raised when a requested repository path does not exist.
- `PathNotDirectoryError` (class): summary=yes, examples=no — Raised when a repository path is expected to be a directory but is not.
- `GitOperationError` (class): summary=yes, examples=yes — Base exception for Git operation errors.
- `RuntimeLifecycleError` (class): summary=yes, examples=no — Raised when a runtime fails to initialize or shut down.
- `RuntimeUnavailableError` (class): summary=yes, examples=no — Raised when a runtime dependency is missing or disabled.
- `VectorIndexStateError` (class): summary=yes, examples=no — Raised when a FAISS index is missing or not ready.
- `VectorIndexIncompatibleError` (class): summary=yes, examples=no — Raised when FAISS assets (dimension, factory) are incompatible.

## Tags

low-coverage, public-api
