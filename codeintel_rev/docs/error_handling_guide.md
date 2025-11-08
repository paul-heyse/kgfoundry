# Error Handling Architecture Guide

**Version**: 1.0.0  
**Last Updated**: 2025-01-08

## Overview

This guide documents the standardized error handling architecture for the CodeIntel MCP server. All MCP tools use a unified three-layer error handling pattern that ensures consistent error responses with RFC 9457 Problem Details compliance and structured logging.

## Architecture: Three-Layer Pattern

The error handling follows a clean separation of concerns across three layers:

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: Domain Logic (Adapters)                           │
│                                                             │
│  - Pure domain logic that raises typed exceptions          │
│  - No manual error dict construction                       │
│  - Exceptions include structured context                   │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Layer 2: Error Handling Decorator                           │
│                                                             │
│  - @handle_adapter_errors decorator wraps MCP tools        │
│  - Catches ALL exceptions automatically                    │
│  - Converts exceptions → Problem Details → error envelope  │
│  - Logs with structured context                            │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Layer 3: Unified Error Envelope (Client-Facing)             │
│                                                             │
│  - Consistent structure across all tools                   │
│  - Tool-specific fields + error + problem fields           │
│  - RFC 9457 Problem Details compliance                     │
└─────────────────────────────────────────────────────────────┘
```

## Layer 1: Domain Logic (Adapters)

### When to Raise Exceptions

Adapters should **raise exceptions** for all error conditions. Never return error dicts from adapter functions.

**Good Example**:
```python
def open_file(context, path, start_line, end_line):
    """Read file content with optional line slicing.
    
    Raises
    ------
    PathOutsideRepositoryError
        If path escapes repository root.
    FileNotFoundError
        If file doesn't exist or is not a file.
    FileReadError
        If file is binary or has encoding issues.
    InvalidLineRangeError
        If line range parameters are invalid.
    """
    repo_root = context.paths.repo_root
    
    # Path validation (raises on error)
    file_path = resolve_within_repo(repo_root, path, allow_nonexistent=False)
    
    # File type check
    if not file_path.is_file():
        error_msg = f"Not a file: {path}"
        raise FileNotFoundError(error_msg)
    
    # Read content
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        error_msg = "Binary file or encoding error"
        raise FileReadError(error_msg, path=path) from exc
    
    # Success case
    return {"path": path, "content": content, "lines": len(content.splitlines()), "size": len(content)}
```

**Bad Example** (Don't Do This):
```python
def open_file(context, path, start_line, end_line):
    try:
        file_path = resolve_within_repo(repo_root, path)
    except PathOutsideRepositoryError as exc:
        return {"error": str(exc), "path": path}  # ❌ Manual error dict
    
    if not file_path.is_file():
        return {"error": "Not a file", "path": path}  # ❌ Manual error dict
    
    return {"path": path, "content": content}  # Success
```

### Available Exception Types

#### File Operation Errors

**`FileOperationError`** (Base class, 400 Bad Request)
- Use for general file operation failures
- Includes `path` in context

**`FileReadError`** (400 Bad Request)
- Use when file cannot be read due to encoding or binary content
- Inherits from `FileOperationError`

**`InvalidLineRangeError`** (400 Bad Request)
- Use when line range parameters are invalid
- Includes `path`, `start_line`, `end_line` in context

#### Git Operation Errors

**`GitOperationError`** (500 Internal Server Error)
- Use when Git operations fail (blame, log, etc.)
- Includes optional `path` and `git_command` in context

#### Search Operation Errors

**`VectorSearchError`** (503 Service Unavailable)
- Use for FAISS search failures, index not ready, timeouts
- Import from `kgfoundry_common.errors`

**`EmbeddingError`** (503 Service Unavailable)
- Use for vLLM embedding generation failures
- Import from `kgfoundry_common.errors`

### Exception Context

All exceptions should include structured context for debugging:

```python
raise InvalidLineRangeError(
    "start_line must be a positive integer",
    path="src/main.py",
    line_range=(0, 10),
)
# Context automatically includes: {"path": "src/main.py", "start_line": 0, "end_line": 10}
```

### Docstring Requirements

All adapter functions must include a **Raises** section documenting all exception types:

```python
def my_adapter(context, param: str) -> dict:
    """Do something.
    
    Parameters
    ----------
    context : ApplicationContext
        Application context.
    param : str
        Parameter description.
    
    Returns
    -------
    dict
        Result description.
    
    Raises
    ------
    FileNotFoundError
        If file doesn't exist.
    ValueError
        If parameter is invalid.
    """
```

## Layer 2: Error Handling Decorator

### Using the Decorator

All MCP tool functions must be decorated with `@handle_adapter_errors`:

```python
from codeintel_rev.mcp_server.error_handling import handle_adapter_errors

@mcp.tool()
@handle_adapter_errors(
    operation="files:open_file",
    empty_result={"path": "", "content": "", "lines": 0, "size": 0},
)
def open_file(path: str, start_line: int | None, end_line: int | None) -> dict:
    """Read file content.
    
    Error handling is automatic via decorator. All exceptions are caught
    and converted to unified error envelopes with Problem Details.
    """
    context = get_context()
    return files_adapter.open_file(context, path, start_line, end_line)
```

### Decorator Parameters

**`operation`** (str, required)
- Operation identifier in format `"category:operation"`
- Examples: `"files:open_file"`, `"search:text"`, `"git:blame_range"`
- Used for Problem Details `instance` field and structured logging

**`empty_result`** (Mapping[str, object], required)
- Tool-specific result fields with empty/zero values
- These are merged into error envelopes so clients always see the same field structure
- Examples:
  - `open_file`: `{"path": "", "content": "", "lines": 0, "size": 0}`
  - `list_paths`: `{"items": [], "total": 0, "truncated": False}`
  - `blame_range`: `{"blame": []}`
  - `search_text`: `{"matches": [], "total": 0, "truncated": False}`

### Decorator Order

The decorator **MUST** be applied **AFTER** `@mcp.tool()` so FastMCP sees the unwrapped function signature for JSON Schema generation:

```python
@mcp.tool()  # FIRST
@handle_adapter_errors(...)  # SECOND
def my_tool(...):
    ...
```

### Async Function Support

The decorator automatically handles both sync and async functions:

```python
# Sync function
@mcp.tool()
@handle_adapter_errors(operation="test", empty_result={"value": 0})
def sync_tool() -> dict:
    return {"value": 42}

# Async function
@mcp.tool()
@handle_adapter_errors(operation="test", empty_result={"value": 0})
async def async_tool() -> dict:
    return {"value": 42}
```

## Layer 3: Unified Error Envelope

### Success Response

On success, the response contains only tool-specific fields:

```json
{
    "path": "src/main.py",
    "content": "def main():\n    pass",
    "lines": 2,
    "size": 28
}
```

### Error Response

On error, the response includes tool-specific fields (empty/zero values) plus `error` and `problem` fields:

```json
{
    "path": "",
    "content": "",
    "lines": 0,
    "size": 0,
    "error": "File not found: src/main.py",
    "problem": {
        "type": "https://kgfoundry.dev/problems/file-not-found",
        "title": "File Not Found",
        "status": 404,
        "detail": "File not found: src/main.py",
        "instance": "urn:codeintel:files:open_file",
        "code": "file-not-found"
    }
}
```

### Problem Details Structure

All error responses include RFC 9457 Problem Details in the `problem` field:

- **`type`** (str): URI identifying the problem type (e.g., `"https://kgfoundry.dev/problems/file-not-found"`)
- **`title`** (str): Short, human-readable summary
- **`status`** (int): HTTP status code (4xx for client errors, 5xx for server errors)
- **`detail`** (str): Human-readable explanation
- **`instance`** (str): URI identifying the specific occurrence (e.g., `"urn:codeintel:files:open_file"`)
- **`code`** (str): Error code for programmatic handling (e.g., `"file-not-found"`)
- **`extensions`** (dict, optional): Additional context (e.g., `{"path": "src/main.py"}`)

## Exception → Status Code Mapping

| Exception Type | HTTP Status | Error Code | Use Case |
|----------------|-------------|------------|----------|
| `FileNotFoundError` | 404 | `file-not-found` | File doesn't exist |
| `PathOutsideRepositoryError` | 403 | `forbidden` | Path escapes repository root |
| `UnicodeDecodeError` | 415 | `unsupported-encoding` | Binary file or encoding error |
| `ValueError` | 400 | `invalid-parameter` | Invalid parameter value |
| `InvalidLineRangeError` | 400 | `invalid-parameter` | Invalid line range |
| `FileReadError` | 400 | `file-operation-error` | File read failure |
| `GitOperationError` | 500 | `git-operation-error` | Git command failed |
| `VectorSearchError` | 503 | `vector-search-error` | FAISS search failure |
| `EmbeddingError` | 503 | `embedding-error` | Embedding generation failure |
| Unknown Exception | 500 | `internal-error` | Unexpected error |

## Structured Logging

All errors are logged with structured context for observability:

### KgFoundryError Logging

```python
# Logged with with_fields() including:
# - component: "codeintel_mcp"
# - operation: "files:open_file"
# - error_code: "file-operation-error"
# - context: Exception context dict
# Log level: Matches exception severity (WARNING, ERROR, CRITICAL)
```

### Builtin Exception Logging

```python
# FileNotFoundError, ValueError, etc.:
# - component: "codeintel_mcp"
# - operation: "files:open_file"
# - error: Exception message
# Log level: WARNING
```

### Unknown Exception Logging

```python
# Unknown exceptions:
# - component: "codeintel_mcp"
# - operation: "files:open_file"
# - exception_type: "SomeUnknownException"
# Log level: ERROR (includes stack trace)
```

## Testing Patterns

### Testing Exception Raising

Test that adapters raise exceptions on error:

```python
def test_open_file_not_found(mock_context: Mock) -> None:
    """Test open_file raises FileNotFoundError for nonexistent files."""
    with pytest.raises(FileNotFoundError, match="not found"):
        open_file(mock_context, "nonexistent.py")
```

### Testing Exception Context

Verify exception context includes expected fields:

```python
def test_open_file_exception_context(mock_context: Mock) -> None:
    """Test that exceptions include proper context."""
    with pytest.raises(InvalidLineRangeError) as exc_info:
        open_file(mock_context, "README.md", start_line=0, end_line=10)
    
    exc = exc_info.value
    assert exc.context["path"] == "README.md"
    assert exc.context["start_line"] == 0
    assert exc.context["end_line"] == 10
```

### Testing Error Envelopes (MCP Tool Level)

Test that MCP tools return error envelopes with Problem Details:

```python
def test_open_file_tool_error_envelope() -> None:
    """Test that MCP tool returns error envelope on error."""
    result = open_file_tool("nonexistent.py")
    
    assert result["path"] == ""
    assert result["content"] == ""
    assert result["lines"] == 0
    assert result["size"] == 0
    assert "error" in result
    assert "problem" in result
    assert result["problem"]["status"] == 404
    assert result["problem"]["code"] == "file-not-found"
```

## Common Pitfalls

### ❌ Don't Return Error Dicts from Adapters

```python
# ❌ BAD
def open_file(context, path):
    if not path.exists():
        return {"error": "File not found", "path": path}
    return {"path": path, "content": content}

# ✅ GOOD
def open_file(context, path):
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return {"path": path, "content": content}
```

### ❌ Don't Catch Exceptions in Adapters

```python
# ❌ BAD
def open_file(context, path):
    try:
        content = path.read_text()
    except FileNotFoundError:
        return {"error": "File not found"}  # Let decorator handle it!
    return {"content": content}

# ✅ GOOD
def open_file(context, path):
    # Let exceptions propagate - decorator will catch them
    content = path.read_text()
    return {"content": content}
```

### ❌ Don't Forget Empty Result in Decorator

```python
# ❌ BAD
@handle_adapter_errors(operation="files:open_file", empty_result={})  # Missing fields!

# ✅ GOOD
@handle_adapter_errors(
    operation="files:open_file",
    empty_result={"path": "", "content": "", "lines": 0, "size": 0}
)
```

### ❌ Don't Apply Decorator Before @mcp.tool()

```python
# ❌ BAD
@handle_adapter_errors(...)  # Wrong order!
@mcp.tool()
def my_tool(...):
    ...

# ✅ GOOD
@mcp.tool()  # First
@handle_adapter_errors(...)  # Second
def my_tool(...):
    ...
```

## Migration Checklist

When refactoring an adapter to use exception-based error handling:

- [ ] Remove all `return {"error": ...}` statements
- [ ] Replace with appropriate exceptions (`raise FileNotFoundError(...)`)
- [ ] Update docstring to include **Raises** section
- [ ] Add `@handle_adapter_errors` decorator to MCP tool function
- [ ] Specify `empty_result` matching success response structure
- [ ] Update unit tests to expect exceptions instead of error dicts
- [ ] Verify error envelope structure in integration tests

## Examples

### Complete Example: open_file Adapter

**Adapter** (`codeintel_rev/mcp_server/adapters/files.py`):
```python
def open_file(context, path, start_line=None, end_line=None):
    """Read file content with optional line slicing.
    
    Raises
    ------
    PathOutsideRepositoryError
        If path escapes repository root.
    FileNotFoundError
        If file doesn't exist or is not a file.
    FileReadError
        If file is binary or has encoding issues.
    InvalidLineRangeError
        If line range parameters are invalid.
    """
    repo_root = context.paths.repo_root
    
    # Path validation (raises on error)
    file_path = resolve_within_repo(repo_root, path, allow_nonexistent=False)
    
    # File type check
    if not file_path.is_file():
        error_msg = f"Not a file: {path}"
        raise FileNotFoundError(error_msg)
    
    # Read content
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        error_msg = "Binary file or encoding error"
        raise FileReadError(error_msg, path=path) from exc
    
    # Success case
    return {"path": path, "content": content, "lines": len(content.splitlines()), "size": len(content)}
```

**MCP Tool** (`codeintel_rev/mcp_server/server.py`):
```python
@mcp.tool()
@handle_adapter_errors(
    operation="files:open_file",
    empty_result={"path": "", "content": "", "lines": 0, "size": 0},
)
def open_file(path: str, start_line: int | None, end_line: int | None) -> dict:
    """Read file content.
    
    Error handling is automatic via decorator.
    """
    context = get_context()
    return files_adapter.open_file(context, path, start_line, end_line)
```

**Test** (`tests/codeintel_rev/test_files_adapter.py`):
```python
def test_open_file_not_found(mock_context: Mock) -> None:
    """Test open_file raises FileNotFoundError for nonexistent files."""
    with pytest.raises(FileNotFoundError, match="not found"):
        open_file(mock_context, "nonexistent.py")
```

## Troubleshooting

### Problem: Decorator Not Catching Exceptions

**Symptom**: Exceptions propagate to FastMCP instead of being converted to error envelopes.

**Solution**: Ensure decorator is applied correctly and function signature is preserved:
```python
@mcp.tool()
@handle_adapter_errors(...)  # Must be after @mcp.tool()
def my_tool(...):
    ...
```

### Problem: Error Envelope Missing Fields

**Symptom**: Error response doesn't include all tool-specific fields.

**Solution**: Ensure `empty_result` includes all fields from success response:
```python
@handle_adapter_errors(
    operation="files:open_file",
    empty_result={"path": "", "content": "", "lines": 0, "size": 0}  # All fields!
)
```

### Problem: Problem Details Missing

**Symptom**: Error response doesn't include `problem` field.

**Solution**: Ensure decorator is applied - it automatically adds Problem Details to all error responses.

### Problem: Logs Missing Structured Context

**Symptom**: Logs don't include operation, error_code, etc.

**Solution**: Ensure exceptions inherit from `KgFoundryError` or are builtin exceptions (FileNotFoundError, ValueError, etc.) - these are automatically logged with structured context.

## References

- **RFC 9457 Problem Details**: [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457.html)
- **Error Codes**: `src/kgfoundry_common/errors/codes.py`
- **Exception Hierarchy**: `codeintel_rev/errors.py`
- **Error Handling Module**: `codeintel_rev/mcp_server/error_handling.py`
- **Specification**: `openspec/changes/codeintel-error-handling-standardization/specs/codeintel-error-envelope/spec.md`

