# mcp_server/error_handling.py

## Docstring

```
Centralized error handling for CodeIntel MCP server.

This module provides the unified error handling infrastructure for all MCP tools,
ensuring consistent error responses with RFC 9457 Problem Details compliance and
structured logging for observability.

Architecture
------------
The error handling follows a three-layer pattern:

1. **Adapter Layer**: Pure domain logic that raises typed exceptions
2. **Decorator Layer**: Automatic exception → envelope conversion
3. **Client Layer**: Uniform error envelope with Problem Details

All MCP tool functions are decorated with ``@handle_adapter_errors`` which
catches all exceptions, converts them to Problem Details, logs with structured
context, and returns a unified error envelope.

Examples
--------
Applying decorator to MCP tool:

>>> @mcp.tool()
>>> @handle_adapter_errors(
...     operation="files:open_file", empty_result={"path": "", "content": "", "lines": 0, "size": 0}
... )
... def open_file(path: str, start_line: int | None, end_line: int | None) -> dict:
...     context = get_context()
...     return files_adapter.open_file(context, path, start_line, end_line)

Error envelope structure:

>>> # On success:
>>> {"path": "src/main.py", "content": "...", "lines": 10, "size": 234}
>>>
>>> # On error (FileNotFoundError):
>>> {
...     "path": "",
...     "content": "",
...     "lines": 0,
...     "size": 0,
...     "error": "File not found: src/main.py",
...     "problem": {
...         "type": "https://kgfoundry.dev/problems/file-not-found",
...         "title": "File Not Found",
...         "status": 404,
...         "detail": "File not found: src/main.py",
...         "instance": "urn:codeintel:files:open_file",
...         "code": "file-not-found",
...     },
... }
```

## Imports

- from **__future__** import annotations
- from **(absolute)** import inspect
- from **collections.abc** import Awaitable, Callable, Mapping
- from **dataclasses** import dataclass
- from **functools** import wraps
- from **http** import HTTPStatus
- from **typing** import TYPE_CHECKING, TypeVar, cast
- from **codeintel_rev.errors** import PathNotDirectoryError, PathNotFoundError
- from **codeintel_rev.io.path_utils** import PathOutsideRepositoryError
- from **kgfoundry_common.errors** import KgFoundryError
- from **kgfoundry_common.logging** import get_logger, with_fields
- from **kgfoundry_common.problem_details** import build_problem_details
- from **kgfoundry_common.problem_details** import ProblemDetails

## Definitions

- class: `ProblemMapping` (line 111)
- function: `format_error_response` (line 168)
- function: `convert_exception_to_envelope` (line 226)
- function: `handle_adapter_errors` (line 411)
- function: `decorator` (line 532)
- function: `async_wrapper` (line 560)
- function: `sync_wrapper` (line 621)

## Tags

overlay-needed, public-api
