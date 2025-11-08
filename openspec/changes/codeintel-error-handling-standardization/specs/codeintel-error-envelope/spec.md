# Capability: codeintel-error-envelope

**Status**: Draft  
**Version**: 1.0.0  
**Owner**: CodeIntel Team  
**Last Updated**: 2025-11-08

## Purpose

Define requirements for consistent error handling and response formats across all CodeIntel MCP tools, ensuring RFC 9457 Problem Details compliance, structured logging, and exceptional observability.

## Scope

This capability covers:
- Unified error envelope structure for all MCP tool responses
- Exception-based error handling in adapters
- Automatic exception → Problem Details conversion
- Structured logging for all error conditions
- Domain-specific exception hierarchy

Out of scope (future capabilities):
- HTTP exception handlers (FastAPI-level)
- Automatic retry logic for transient errors
- Partial results with warnings
- Client-side error handling SDKs

## Requirements

### FR-ERR-001: Unified Error Envelope Structure

**Priority**: MUST  
**Added**: 2025-11-08

All MCP tool responses MUST include error and problem fields when errors occur.

**Acceptance Criteria**:
- Every error response includes `error: str` field (human-readable message)
- Every error response includes `problem: ProblemDetailsDict` field (RFC 9457)
- Tool-specific result fields present but empty on error (e.g., `{"matches": [], "total": 0}`)
- Success responses do NOT include error/problem fields
- Error envelope structure identical across all tools (text_search, semantic_search, files, history)

**Verification**:
- Unit test: Verify error envelope has required fields
- Integration test: Call each tool with error-inducing parameters, verify structure
- Schema validation: Error envelopes validate against TypedDict schemas

---

### FR-ERR-002: RFC 9457 Problem Details Compliance

**Priority**: MUST  
**Added**: 2025-11-08

All Problem Details payloads MUST conform to RFC 9457 and validate against canonical schema.

**Acceptance Criteria**:
- Problem Details include required fields: type, title, status, detail, instance
- Problem Details include recommended field: code (error code string)
- Problem Details may include extensions (optional context dict)
- Type URIs follow format: `https://kgfoundry.dev/problems/{code}`
- Status codes follow HTTP semantics (4xx for client errors, 5xx for server errors)
- All payloads validate against `schema/common/problem_details.json`

**Verification**:
- Unit test: Generate Problem Details for each exception type, validate against schema
- Integration test: Verify type URIs follow format
- Schema validation test: Use jsonschema library to validate all Problem Details

---

### FR-ERR-003: Exception-Based Adapter Implementation

**Priority**: MUST  
**Added**: 2025-11-08

Adapter functions MUST raise exceptions on error instead of returning error dicts.

**Acceptance Criteria**:
- Adapters raise exceptions for all error conditions (no `return {"error": ...}`)
- Adapters use typed exceptions from domain hierarchy (FileOperationError, GitOperationError, etc.)
- Exceptions include structured context (path, line_range, git_command, etc.)
- Success case returns result dict (no error fields)
- Docstrings include Raises section documenting all exception types

**Verification**:
- Code review: Verify zero `return {"error": ...}` statements in adapters
- Unit test: Assert exceptions raised for error scenarios
- Docstring check: Verify Raises section present and complete

---

### FR-ERR-004: Automatic Exception Conversion

**Priority**: MUST  
**Added**: 2025-11-08

MCP tool functions MUST use error handling decorator to convert exceptions to error envelopes.

**Acceptance Criteria**:
- All MCP tool functions decorated with `@handle_adapter_errors`
- Decorator catches ALL exceptions (KgFoundryError, FileNotFoundError, UnicodeDecodeError, unknown)
- Decorator converts exception → Problem Details → error envelope
- Decorator returns envelope (does not re-raise exception)
- Decorator preserves function signature (for FastMCP schema generation)
- Unknown exceptions mapped to 500 Internal Error with safe message

**Verification**:
- Code review: Verify decorator applied to all MCP tools
- Unit test: Verify decorator catches all exception types
- Integration test: Inject unknown exception, verify 500 response

---

### FR-ERR-005: Domain Exception Hierarchy

**Priority**: MUST  
**Added**: 2025-11-08

CodeIntel MUST define domain-specific exceptions with automatic Problem Details mapping.

**Acceptance Criteria**:
- `FileOperationError` base class (400 Bad Request)
  - `FileReadError` (415 Unsupported Media Type for binary/encoding)
  - `InvalidLineRangeError` (400 Bad Request with line_range context)
- `GitOperationError` base class (500 Internal Server Error)
  - Includes path and git_command context
- All exceptions inherit from `KgFoundryError`
- All exceptions include structured context (dict)
- All exceptions provide `to_problem_details()` method via inheritance

**Verification**:
- Unit test: Instantiate each exception, verify context and HTTP status
- Unit test: Call `to_problem_details()`, verify structure
- Type check: Verify all exceptions inherit from KgFoundryError

---

### FR-ERR-006: Structured Logging for All Errors

**Priority**: MUST  
**Added**: 2025-11-08

All error conditions MUST be logged with structured context for observability.

**Acceptance Criteria**:
- KgFoundryError: Logged with `with_fields()` including operation, error_code, component
- KgFoundryError: Log level matches exception severity (WARNING, ERROR, CRITICAL)
- KgFoundryError: Context dict logged in extra fields
- FileNotFoundError: Logged at WARNING level with operation
- UnicodeDecodeError: Logged at WARNING level with encoding and reason
- ValueError: Logged at WARNING level with operation
- Unknown exceptions: Logged at EXCEPTION level (includes stack trace) with exception_type
- No sensitive data in logs (paths sanitized if needed)

**Verification**:
- Unit test: Mock logger, verify structured fields for each exception type
- Unit test: Verify log levels appropriate
- Integration test: Capture logs, verify no sensitive data

---

### FR-ERR-007: HTTP Status Code Mapping

**Priority**: MUST  
**Added**: 2025-11-08

Exceptions MUST map to appropriate HTTP status codes following REST semantics.

**Acceptance Criteria**:
- FileNotFoundError → 404 Not Found
- UnicodeDecodeError → 415 Unsupported Media Type
- ValueError, InvalidLineRangeError → 400 Bad Request
- PathOutsideRepositoryError → 403 Forbidden
- VectorSearchError, EmbeddingError → 503 Service Unavailable
- GitOperationError → 500 Internal Server Error
- Unknown exceptions → 500 Internal Server Error
- KgFoundryError subclasses use defined http_status field

**Verification**:
- Unit test: Verify each exception maps to correct status code
- Integration test: Verify Problem Details status field matches

---

### FR-ERR-008: Error Code Consistency

**Priority**: MUST  
**Added**: 2025-11-08

All errors MUST include error code string for programmatic error handling.

**Acceptance Criteria**:
- Error codes follow kebab-case format (e.g., "file-not-found", "invalid-parameter")
- Error codes match Problem Details type URI suffix
- KgFoundryError subclasses define error code via ErrorCode enum
- Builtin exceptions (FileNotFoundError, ValueError) mapped to standard codes
- Error codes documented in capability spec

**Verification**:
- Unit test: Verify error code present in Problem Details
- Unit test: Verify code matches type URI suffix
- Documentation review: All codes documented

---

### FR-ERR-009: Error Context Preservation

**Priority**: MUST  
**Added**: 2025-11-08

Exceptions MUST preserve context information for debugging and observability.

**Acceptance Criteria**:
- FileOperationError includes path in context
- InvalidLineRangeError includes path, start_line, end_line in context
- GitOperationError includes path and git_command in context
- VectorSearchError includes relevant index/query context
- Context dict included in Problem Details extensions
- Cause chains preserved (raise ... from exc)
- Context does not include sensitive data (passwords, tokens)

**Verification**:
- Unit test: Verify context fields present in exception and Problem Details
- Unit test: Verify cause chains preserved
- Security review: No sensitive data in context

---

### FR-ERR-010: Backward Compatibility

**Priority**: MUST  
**Added**: 2025-11-08

Error envelope changes MUST maintain backward compatibility with existing clients.

**Acceptance Criteria**:
- Tool-specific result fields always present (even when empty on error)
- Error field already exists in most responses (no breaking change)
- Problem field is additive (clients ignoring it continue to work)
- Success response structure unchanged
- Field types unchanged (error is string, problem is dict)

**Verification**:
- Integration test: Verify old client code continues to work
- Schema comparison: Success response structure unchanged
- Unit test: Verify all tool-specific fields present in error responses

---

### FR-ERR-011: Empty Result Specification

**Priority**: MUST  
**Added**: 2025-11-08

Error handling decorator MUST merge empty result fields correctly.

**Acceptance Criteria**:
- `open_file` empty result: `{"path": "", "content": "", "lines": 0, "size": 0}`
- `list_paths` empty result: `{"items": [], "total": 0, "truncated": False}`
- `blame_range` empty result: `{"blame": []}`
- `file_history` empty result: `{"commits": []}`
- `search_text` empty result: `{"matches": [], "total": 0, "truncated": False}`
- `semantic_search` empty result: `{"findings": [], "answer": "", "confidence": 0.0}`
- Empty result fields have appropriate types (empty string, empty list, zero)

**Verification**:
- Unit test: Verify empty result merged correctly for each tool
- Type check: Verify field types match success response types

---

### FR-ERR-012: Decorator Operation Naming

**Priority**: SHOULD  
**Added**: 2025-11-08

Operation identifiers SHOULD follow consistent naming convention.

**Acceptance Criteria**:
- Format: `"category:operation"` (e.g., "files:open_file", "search:text")
- Categories: files, search, git, semantic
- Operation names match MCP tool function names
- Operation string used in Problem Details instance field
- Operation string used in structured logging

**Verification**:
- Code review: Verify operation strings follow format
- Unit test: Verify operation in Problem Details instance
- Log review: Verify operation in structured logs

---

### FR-ERR-013: Error Envelope Schema Validation

**Priority**: SHOULD  
**Added**: 2025-11-08

Error envelopes SHOULD validate against TypedDict schemas.

**Acceptance Criteria**:
- `BaseErrorFields` TypedDict defines error and problem fields
- Tool-specific response TypedDicts inherit from BaseErrorFields
- TypedDict schemas match actual response structure
- Pyright validates error envelope construction

**Verification**:
- Type check: Pyright reports zero errors for error envelope construction
- Unit test: Construct error envelopes, verify types match TypedDict

---

### FR-ERR-014: Exception Message Quality

**Priority**: SHOULD  
**Added**: 2025-11-08

Exception messages SHOULD be clear, actionable, and user-friendly.

**Acceptance Criteria**:
- Messages explain what went wrong (e.g., "File not found: src/main.py")
- Messages include relevant context (path, line numbers)
- Messages do not expose internal implementation details
- Messages are grammatically correct and professional
- Messages suitable for end-user display

**Verification**:
- Code review: Review all exception messages for clarity
- User testing: Verify messages are understandable

---

### FR-ERR-015: Decorator Documentation

**Priority**: SHOULD  
**Added**: 2025-11-08

Error handling decorator SHOULD be comprehensively documented.

**Acceptance Criteria**:
- Docstring includes Parameters, Returns, Notes, Examples sections
- Examples show real MCP tool usage
- Benefits of decorator explained
- When to use decorator explained (all MCP tools)
- Empty result parameter usage explained

**Verification**:
- Documentation review: Verify docstring complete
- Code review: Verify examples are correct and runnable

---

## Data Contracts

### Error Envelope Structure

All MCP tool error responses follow this structure:

```python
{
    # Tool-specific result fields (empty on error)
    "matches": [],        # For search_text
    "blame": [],          # For blame_range
    "findings": [],       # For semantic_search
    "path": "",           # For open_file
    # ... other tool fields ...
    
    # Error fields (present on all errors)
    "error": "Human-readable error message",
    "problem": {
        "type": "https://kgfoundry.dev/problems/{code}",
        "title": "Error Title",
        "status": 404,  # HTTP status code
        "detail": "Detailed error message",
        "instance": "urn:codeintel:category:operation",
        "code": "error-code",
        "extensions": {
            # Optional context
            "path": "src/main.py",
            "exception_type": "FileNotFoundError"
        }
    }
}
```

### Exception → Status Code Mapping

| Exception Type | HTTP Status | Error Code | Type URI |
|----------------|-------------|------------|----------|
| FileNotFoundError | 404 | file-not-found | `.../file-not-found` |
| UnicodeDecodeError | 415 | unsupported-encoding | `.../unsupported-encoding` |
| ValueError | 400 | invalid-parameter | `.../invalid-parameter` |
| InvalidLineRangeError | 400 | invalid-parameter | `.../invalid-parameter` |
| PathOutsideRepositoryError | 403 | forbidden | `.../forbidden` |
| FileReadError | 415 | unsupported-encoding | `.../unsupported-encoding` |
| GitOperationError | 500 | git-operation-error | `.../git-operation-error` |
| VectorSearchError | 503 | vector-search-error | `.../vector-search-error` |
| EmbeddingError | 503 | embedding-error | `.../embedding-error` |
| Unknown Exception | 500 | internal-error | `.../internal-error` |

### Exception Context Fields

**FileOperationError**:
```python
{
    "path": str  # File path that caused error
}
```

**InvalidLineRangeError**:
```python
{
    "path": str,
    "start_line": int | None,
    "end_line": int | None
}
```

**GitOperationError**:
```python
{
    "path": str | None,
    "git_command": str | None  # "blame", "log", etc.
}
```

**VectorSearchError**:
```python
{
    "query": str,
    "faiss_index": str,
    # ... other search context
}
```

---

## Observability

### Metrics

**Counter**: `codeintel_errors_total`  
Description: Total number of errors by type and operation.  
Labels: `error_code`, `operation`, `http_status`  
Target: Monitor for spikes (rate change >2x)

**Histogram**: `codeintel_error_handling_duration_seconds`  
Description: Time spent in error handling decorator.  
Labels: `operation`  
Target: p95 <0.01s (error handling should be fast)

### Logs

**Event**: KgFoundryError  
Level: Varies (WARNING, ERROR, CRITICAL per exception)  
Message: `exception.message`  
Fields:
- `component`: "codeintel_mcp"
- `operation`: "files:open_file"
- `error_code`: "file-not-found"
- `context`: Exception context dict

**Event**: FileNotFoundError  
Level: WARNING  
Message: `"File not found"`  
Fields:
- `component`: "codeintel_mcp"
- `operation`: "files:open_file"
- `error`: Exception message

**Event**: Unknown Exception  
Level: ERROR  
Message: `"Unexpected error"`  
Fields:
- `component`: "codeintel_mcp"
- `operation`: "files:open_file"
- `exception_type`: "SomeUnknownException"
- Stack trace included

---

## Testing Strategy

### Unit Tests

**Exception Conversion Tests**:
- Test each exception type → Problem Details conversion
- Verify HTTP status codes
- Verify error codes
- Verify context in extensions
- Verify structured logging

**Decorator Tests**:
- Test success path (no exception)
- Test exception handling (various types)
- Test function signature preservation
- Test async function compatibility
- Test empty result merging

**Schema Validation Tests**:
- Validate Problem Details against RFC 9457 schema
- Validate error envelopes against TypedDict schemas

### Integration Tests

**Error Scenario Tests**:
- Call each MCP tool with error-inducing parameters
- Verify error envelope structure
- Verify Problem Details fields
- Verify HTTP status codes

**End-to-End Tests**:
- Test file not found scenario
- Test invalid parameters scenario
- Test Git operation failure
- Test encoding error
- Test search timeout
- Test FAISS not ready
- Test unknown exception handling

### Load Tests

**Error Rate Under Load**:
- Generate errors at 10% of normal traffic
- Verify error handling doesn't degrade performance
- Verify structured logging at scale

---

## Migration & Rollout

### Backward Compatibility

**Breaking Changes**: None

**Additive Changes**:
- `problem` field added to all error responses
- Error envelope structure standardized (but existing fields preserved)

### Rollout Plan

**Week 1**: Deploy error infrastructure
- Exception hierarchy
- Error handling decorator
- Exception conversion logic

**Week 2**: Refactor adapters
- Files adapters (open_file, list_paths)
- History adapters (blame_range, file_history)
- Search adapters (search_text, semantic_search)

**Verification**: Integration tests verify backward compatibility

### Client Migration

**No Migration Required**: All changes are server-side. Existing clients continue to work.

**Optional Enhancements**: Clients can read `problem` field for structured error information (error codes, HTTP status, context).

---

## Dependencies

- **kgfoundry_common.errors**: Base exception hierarchy and ErrorCode enum
- **kgfoundry_common.problem_details**: Problem Details construction and validation
- **kgfoundry_common.logging**: Structured logging utilities
- **Phase 1 Complete**: ApplicationContext available in all adapters
- **Phase 3 Complete**: GitClient/AsyncGitClient available

---

## Examples

### Success Response (open_file)

```json
{
    "path": "src/main.py",
    "content": "def main():\n    pass",
    "lines": 2,
    "size": 28
}
```

### Error Response (open_file - file not found)

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

### Error Response (open_file - invalid line range)

```json
{
    "path": "",
    "content": "",
    "lines": 0,
    "size": 0,
    "error": "start_line must be a positive integer",
    "problem": {
        "type": "https://kgfoundry.dev/problems/invalid-parameter",
        "title": "Invalid Parameter",
        "status": 400,
        "detail": "start_line must be a positive integer",
        "instance": "urn:codeintel:files:open_file",
        "code": "invalid-parameter",
        "extensions": {
            "path": "src/main.py",
            "start_line": 0,
            "end_line": 10
        }
    }
}
```

### Error Response (search_text - timeout)

```json
{
    "matches": [],
    "total": 0,
    "truncated": false,
    "error": "Search timeout",
    "problem": {
        "type": "https://kgfoundry.dev/problems/vector-search-error",
        "title": "Vector Search Error",
        "status": 503,
        "detail": "Search timeout",
        "instance": "urn:codeintel:search:text",
        "code": "vector-search-error",
        "extensions": {
            "query": "def main"
        }
    }
}
```

---

## Glossary

**Error Envelope**: Response structure containing both tool-specific result fields and error/problem fields.

**Problem Details**: RFC 9457 standardized error format with type, title, status, detail, instance, code, extensions.

**Exception-Based Flow**: Pattern where adapters raise exceptions and decorator converts to error envelopes.

**Structured Logging**: Logging with key-value pairs in extra fields for machine readability.

**Empty Result**: Tool-specific fields with empty/zero values used in error envelopes.

**Operation Identifier**: String identifying the MCP tool operation (format: "category:operation").

**Error Code**: Kebab-case string identifying error type (e.g., "file-not-found").

