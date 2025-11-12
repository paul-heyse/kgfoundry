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

- variable: `LOGGER` (line 72)
- variable: `COMPONENT_NAME` (line 73)
- variable: `F` (line 75)
- class: `ProblemMapping` (line 111)
- variable: `EXCEPTION_TO_ERROR_CODE` (line 152)
- function: `format_error_response` (line 168)
- function: `convert_exception_to_envelope` (line 226)
- function: `handle_adapter_errors` (line 411)

## Dependency Graph

- **fan_in**: 3
- **fan_out**: 3
- **cycle_group**: 57

## Declared Exports (__all__)

EXCEPTION_TO_ERROR_CODE, convert_exception_to_envelope, format_error_response, handle_adapter_errors

## Doc Metrics

- **summary**: Centralized error handling for CodeIntel MCP server.
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

## Hotspot Score

- score: 2.21

## Side Effects

- network

## Complexity

- branches: 17
- cyclomatic: 18
- loc: 687

## Doc Coverage

- `ProblemMapping` (class): summary=yes, examples=no — Mapping from exception type to RFC 9457 Problem Details metadata.
- `format_error_response` (function): summary=yes, params=ok, examples=no — Return Problem Details payload for the provided exception.
- `convert_exception_to_envelope` (function): summary=yes, params=ok, examples=yes — Convert exception to unified error envelope with Problem Details.
- `handle_adapter_errors` (function): summary=yes, params=ok, examples=yes — Convert adapter exceptions to unified error envelopes.

## Tags

low-coverage, public-api
