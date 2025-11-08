# Consistent Error Handling and Responses (Phase 4)

**Status**: Ready for Implementation  
**Phase**: 4 of 4 (Code Quality & Maintainability)  
**Est. Duration**: 2 weeks (50 hours)  
**Owner**: CodeIntel Team  
**Dependencies**: Phases 1-3 (ApplicationContext, scope management, performance)

## Problem Statement

The CodeIntel MCP server handles errors gracefully (returning JSON with error messages rather than throwing uncaught exceptions), but **error representation is inconsistent across adapters**, creating confusion for clients and duplicating error-handling logic across the codebase.

### Current Error Handling Inconsistencies

**1. Three Different Error Response Formats**:

| Adapter | Format | Fields | Problem Details Support |
|---------|--------|--------|-------------------------|
| `text_search` | `{"matches": [], "total": 0, "error": "...", "problem": {...}}` | RFC 9457 `problem` field with full Problem Details | ✅ Yes |
| `semantic_search` | `AnswerEnvelope` with `{"findings": [], "answer": "error msg", "confidence": 0.0, "problem": {...}}` | RFC 9457 embedded in envelope | ✅ Yes |
| `files` + `history` | `{"error": "...", "path": "..."}` or `{"blame": [], "error": "..."}` | Simple error string only | ❌ No |

**Impact**: Clients must handle 3 different error formats. No uniform way to extract error codes, HTTP status, or structured context.

**2. Duplicated Error Formatting Logic**:

- `text_search.py`: `_error_response()` helper (lines 352-381)
- `semantic.py`: `_error_envelope()` helper (lines 480-521)
- Files/history: Inline `{"error": ...}` dicts scattered throughout

**Impact**: 50+ lines of duplicated code. Changes to error structure require updates in multiple places.

**3. Return-Based Error Handling vs. Exception-Based**:

- Adapters **never raise exceptions** - they catch all errors and return error dicts
- Lower-level I/O functions **do raise exceptions** (e.g., `resolve_within_repo` raises `PathOutsideRepositoryError`)
- Result: 10-15 lines of `try/except` + manual error dict construction per adapter function

**Example from `open_file` (lines 360-408)**:
```python
try:
    file_path = resolve_within_repo(repo_root, path, allow_nonexistent=False)
except PathOutsideRepositoryError as exc:
    return {"error": str(exc), "path": path}  # Manual error dict
except FileNotFoundError:
    return {"error": "File not found", "path": path}  # Manual error dict

if not file_path.is_file():
    return {"error": "Not a file", "path": path}  # Manual error dict

try:
    content = file_path.read_text(encoding="utf-8")
except UnicodeDecodeError:
    return {"error": "Binary file or encoding error", "path": path}  # Manual error dict

# 4 separate error paths, all manually constructed
```

**Impact**: Error handling accounts for 40-50% of adapter code. Difficult to ensure consistent error structure.

**4. Inconsistent Logging**:

- `text_search` logs errors with structured context using `with_fields()` (lines 368-374)
- `semantic_search` logs errors with structured context (lines 503-509)
- `files` and `history` use basic `LOGGER.warning()` without structured fields
- Some errors logged, others not

**Impact**: Inconsistent observability. Hard to correlate errors across adapters. Missing error codes/context in logs.

### Why This Matters

1. **Client Confusion**: Clients must parse 3 different error formats, leading to brittle error handling code
2. **Maintenance Burden**: Changing error structure requires touching 10+ files
3. **Observability Gaps**: Inconsistent logging makes debugging difficult
4. **Best Practice Violation**: RFC 9457 Problem Details exists but not universally applied
5. **Code Duplication**: 100+ lines of duplicated error handling logic

## Proposed Solution

**Standardize on a single, unified error response format across all adapters**, backed by RFC 9457 Problem Details and the existing `KgFoundryError` exception hierarchy.

### Three-Layer Error Handling Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: Exceptions (Pure Domain Logic)                    │
│  - Adapters raise typed exceptions (KgFoundryError hierarchy)│
│  - No manual error dict construction                         │
│  - EAFP style: raise early, catch once                       │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Layer 2: MCP Tool Decorator (Single Conversion Point)      │
│  - @mcp.tool() decorator catches all KgFoundryError          │
│  - Converts exception → unified error envelope               │
│  - Logs with structured context (error code, HTTP status)    │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│  Layer 3: Unified Error Envelope (Client-Facing)            │
│  - Single error response format for all tools                │
│  - RFC 9457 Problem Details embedded                         │
│  - Tool-specific result fields empty on error                │
└─────────────────────────────────────────────────────────────┘
```

### Key Design Decisions

**1. Unified Error Envelope Format**:

All adapters return the **same base structure** with tool-specific result fields:

```python
{
    "matches": [],        # Empty for text_search on error
    "blame": [],          # Empty for blame_range on error
    "findings": [],       # Empty for semantic_search on error
    # ... other tool-specific fields ...
    "error": "Human-readable message",
    "problem": {
        "type": "https://kgfoundry.dev/problems/file-not-found",
        "title": "File Not Found",
        "status": 404,
        "detail": "File 'src/main.py' not found in repository",
        "instance": "urn:codeintel:files:open_file",
        "code": "file-not-found",
        "extensions": {"path": "src/main.py"}
    }
}
```

**Benefits**:
- Clients always check same fields (`error`, `problem`)
- Tool-specific fields present but empty on error (backward compatible)
- RFC 9457 Problem Details provides structured error metadata

**2. Exception-Based Adapters**:

Adapters **raise exceptions** instead of returning error dicts:

```python
# Before (return-based)
def open_file(context, path, start_line, end_line):
    try:
        file_path = resolve_within_repo(repo_root, path)
    except PathOutsideRepositoryError as exc:
        return {"error": str(exc), "path": path}
    except FileNotFoundError:
        return {"error": "File not found", "path": path}
    # ... 4 more error paths ...

# After (exception-based)
def open_file(context, path, start_line, end_line):
    # Raises PathOutsideRepositoryError or FileNotFoundError
    file_path = resolve_within_repo(repo_root, path)
    
    # Raises FileNotFoundError if not a file
    if not file_path.is_file():
        raise FileNotFoundError(f"Not a file: {path}")
    
    # Raises UnicodeDecodeError on encoding issues
    return {"path": path, "content": file_path.read_text(), ...}
```

**MCP Tool Decorator Catches All**:

```python
@mcp.tool()
@handle_adapter_errors(empty_result={"path": "", "content": ""})
def open_file_tool(path: str, start_line: int | None, end_line: int | None) -> dict:
    context = get_context()
    return open_file(context, path, start_line, end_line)
```

**Benefits**:
- Adapter code reduced by 40-50% (no manual error dict construction)
- Single error handling point (decorator) ensures consistency
- Easier to test (can assert exceptions instead of parsing dicts)

**3. Centralized Error Conversion**:

Single module (`codeintel_rev/mcp_server/error_handling.py`) converts exceptions → error envelopes:

```python
def convert_exception_to_envelope(
    exc: Exception,
    operation: str,
    empty_result: dict[str, object],
) -> dict:
    """Convert exception to unified error envelope.
    
    Maps exception to Problem Details, adds structured logging,
    returns tool-specific envelope with empty results + error fields.
    """
    if isinstance(exc, KgFoundryError):
        problem = exc.to_problem_details(instance=operation)
        with with_fields(LOGGER, operation=operation, error_code=exc.code.value) as adapter:
            adapter.log(exc.log_level, exc.message, extra={"context": exc.context})
    elif isinstance(exc, FileNotFoundError):
        problem = build_problem_details(
            type="https://kgfoundry.dev/problems/file-not-found",
            title="File Not Found",
            status=404,
            detail=str(exc),
            instance=operation,
            code="file-not-found",
        )
        LOGGER.warning("File not found", extra={"operation": operation, "error": str(exc)})
    else:
        # Unknown exception → generic server error
        problem = build_problem_details(
            type="https://kgfoundry.dev/problems/internal-error",
            title="Internal Error",
            status=500,
            detail=str(exc),
            instance=operation,
            code="internal-error",
            extensions={"exception_type": type(exc).__name__},
        )
        LOGGER.exception("Unexpected error", extra={"operation": operation})
    
    return {
        **empty_result,  # Tool-specific empty fields
        "error": problem["detail"],
        "problem": problem,
    }
```

**Benefits**:
- Single place to change error format
- Guaranteed structured logging for all errors
- Automatic Problem Details generation
- Handles unknown exceptions gracefully

**4. Domain-Specific Exceptions**:

Introduce CodeIntel-specific exceptions for clearer semantics:

```python
# codeintel_rev/errors.py (NEW)

class FileOperationError(KgFoundryError):
    """Base for file operation errors."""
    def __init__(self, message: str, path: str, cause: Exception | None = None):
        super().__init__(
            message,
            code=ErrorCode.FILE_OPERATION_ERROR,
            http_status=400,
            context={"path": path},
            cause=cause,
        )

class FileReadError(FileOperationError):
    """Raised when file cannot be read (binary, encoding issues)."""
    pass

class InvalidLineRangeError(FileOperationError):
    """Raised when line range is invalid."""
    pass

class GitOperationError(KgFoundryError):
    """Base for Git operation errors."""
    def __init__(self, message: str, path: str | None = None, cause: Exception | None = None):
        super().__init__(
            message,
            code=ErrorCode.GIT_OPERATION_ERROR,
            http_status=500,
            context={"path": path} if path else {},
            cause=cause,
        )
```

**Benefits**:
- Clearer error semantics (`InvalidLineRangeError` vs `{"error": "start_line must be positive"}`)
- Automatic Problem Details mapping
- Consistent HTTP status codes

## Success Criteria

✅ **Uniform Error Format**:
- All adapters return same error envelope structure
- `error` and `problem` fields present in all error responses
- Tool-specific result fields empty on error

✅ **RFC 9457 Compliance**:
- All errors include Problem Details with type, title, status, detail, instance, code
- Problem Details validate against canonical schema

✅ **Structured Logging**:
- All errors logged with operation, error_code, context
- Log level matches exception severity (WARNING for user errors, ERROR for system errors)

✅ **Code Reduction**:
- Adapter error handling code reduced by 40-50%
- Duplicated error formatting logic eliminated (100+ lines removed)

✅ **Backward Compatibility**:
- Existing clients continue to work (tool-specific fields still present, just empty on error)
- `error` field provides human-readable message (existing behavior)

## Out of Scope (Future Work)

- **HTTP Exception Handlers**: FastMCP doesn't expose FastAPI exception handlers, so we handle errors at adapter layer only
- **Retry Logic**: Automatic retries for transient errors (future enhancement)
- **Error Recovery**: Partial results with warnings (future enhancement)
- **Client SDKs**: Language-specific error handling helpers (future)

## Migration Path

**Phase 4a**: Error Infrastructure (Week 1)
- Create unified error envelope schema
- Implement `handle_adapter_errors` decorator
- Add domain-specific exceptions

**Phase 4b**: Adapter Refactoring (Week 2)
- Refactor `files.py` adapters (exception-based)
- Refactor `history.py` adapters (exception-based)
- Standardize `text_search` and `semantic_search` envelopes

**Phase 4c**: Testing & Documentation (Week 2)
- Update unit tests for exception-based adapters
- Integration tests for error scenarios
- Document error handling guide

## Risks & Mitigations

**Risk 1: Breaking Changes for Clients**

**Likelihood**: Low (error field already present)

**Mitigation**:
- Tool-specific fields remain in response (just empty on error)
- `error` field already exists in most responses
- `problem` field is additive (clients ignoring it continue to work)

**Risk 2: Performance Impact of Exception Handling**

**Likelihood**: Negligible (errors are rare)

**Mitigation**:
- Exception handling only on error paths (not hot paths)
- No measurable performance impact (exceptions are ~1-2ms overhead)

**Risk 3: Incomplete Error Coverage**

**Likelihood**: Medium (unexpected exceptions may occur)

**Mitigation**:
- Generic exception handler catches all unknown exceptions
- Logs full stack trace for debugging
- Returns 500 Internal Error with safe message

