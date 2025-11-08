# Implementation Tasks - Phase 4: Error Handling Standardization

## Overview

This document provides an exhaustive breakdown of implementation tasks for Phase 4 error handling standardization. Tasks are organized into 3 phases spanning 2 weeks (50 hours total).

**Phase Breakdown**:
- **Phase 4a**: Error Infrastructure (Week 1) - 15 hours
- **Phase 4b**: Adapter Refactoring (Week 2) - 25 hours
- **Phase 4c**: Testing & Documentation (Week 2) - 10 hours

---

## Phase 4a: Error Infrastructure (Week 1)

### Task 1: Create Domain Exception Hierarchy
**File**: `codeintel_rev/errors.py` (NEW)

**Description**: Define CodeIntel-specific exception types with automatic Problem Details mapping.

**Subtasks**:
1. Create module with comprehensive docstring explaining exception hierarchy
2. Import base classes from `kgfoundry_common.errors`:
   ```python
   from kgfoundry_common.errors import ErrorCode, KgFoundryError
   ```
3. Define `FileOperationError` base class:
   ```python
   class FileOperationError(KgFoundryError):
       def __init__(self, message: str, path: str, cause: Exception | None = None):
           super().__init__(
               message,
               code=ErrorCode.FILE_OPERATION_ERROR,
               http_status=400,
               context={"path": path},
               cause=cause,
           )
   ```
4. Define `FileReadError` subclass (binary/encoding issues)
5. Define `InvalidLineRangeError` subclass with line_range context
6. Define `GitOperationError` base class with path and git_command context
7. Add comprehensive NumPy docstrings with Parameters, Examples, Notes
8. Add `__all__` export list
9. Register error codes in `kgfoundry_common/errors/codes.py` if needed

**Acceptance**:
- All exceptions inherit from `KgFoundryError`
- HTTP status codes appropriate (400 for user errors, 500 for system errors)
- Context includes relevant metadata (path, line_range, git_command)
- Docstrings include Examples sections with usage
- Pyright reports zero errors

**Time Estimate**: 2 hours

---

### Task 2: Create Error Envelope Schemas
**File**: `codeintel_rev/mcp_server/schemas.py` (UPDATED)

**Description**: Add base error fields TypedDict that all response schemas inherit from.

**Subtasks**:
1. Define `BaseErrorFields` TypedDict:
   ```python
   class BaseErrorFields(TypedDict, total=False):
       """Base fields present in ALL error responses."""
       error: str  # Human-readable message
       problem: ProblemDetailsDict  # RFC 9457 Problem Details
   ```
2. Update existing response schemas to inherit from `BaseErrorFields`:
   - `Match` (already defined, no changes needed)
   - Create `OpenFileResponse(BaseErrorFields)` if not exists
   - Create `BlameRangeResponse(BaseErrorFields)` if not exists
   - Create `FileHistoryResponse(BaseErrorFields)` if not exists
   - Create `SearchTextResponse(BaseErrorFields)` if not exists
3. Update `AnswerEnvelope` to include `problem: ProblemDetailsDict` field (may already exist)
4. Add comprehensive docstrings explaining success vs error field population
5. Add Examples section showing both success and error responses

**Acceptance**:
- All response schemas have `error` and `problem` fields (via inheritance or direct)
- Tool-specific fields clearly documented
- Examples show both success and error cases
- Pyright clean

**Time Estimate**: 1.5 hours

---

### Task 3: Implement Exception Conversion Function
**File**: `codeintel_rev/mcp_server/error_handling.py` (NEW)

**Description**: Create single source of truth for converting exceptions to error envelopes.

**Subtasks**:
1. Create module with comprehensive docstring
2. Import required types:
   ```python
   from kgfoundry_common.errors import KgFoundryError
   from kgfoundry_common.logging import get_logger, with_fields
   from kgfoundry_common.problem_details import build_problem_details
   ```
3. Implement `convert_exception_to_envelope()` function:
   - Handle `KgFoundryError` (use `to_problem_details()`)
   - Handle `FileNotFoundError` (404, file-not-found)
   - Handle `UnicodeDecodeError` (415, unsupported-encoding)
   - Handle `ValueError` (400, invalid-parameter)
   - Handle `PathOutsideRepositoryError` (403, forbidden)
   - Handle unknown exceptions (500, internal-error)
4. Add structured logging for each exception type:
   - `with_fields()` for KgFoundryError
   - `LOGGER.warning()` for user errors (FileNotFoundError, ValueError)
   - `LOGGER.exception()` for system errors (unknown exceptions)
5. Build error envelope: `{**empty_result, "error": ..., "problem": ...}`
6. Add comprehensive docstring with Parameters, Returns, Notes, Examples
7. Add type annotations for all parameters and return value

**Acceptance**:
- All exception types mapped to Problem Details
- Structured logging for all exceptions
- Error envelope includes empty result fields + error + problem
- Docstring includes Examples section with 3+ examples
- Pyright clean

**Time Estimate**: 3 hours

---

### Task 4: Implement Error Handling Decorator
**File**: `codeintel_rev/mcp_server/error_handling.py` (continued)

**Description**: Create decorator that wraps MCP tool functions with automatic error handling.

**Subtasks**:
1. Implement `handle_adapter_errors()` decorator factory:
   ```python
   def handle_adapter_errors(
       *,
       operation: str,
       empty_result: Mapping[str, object],
   ) -> Callable[[F], F]:
   ```
2. Inner decorator function with `@wraps(func)` for signature preservation
3. Wrapper function with try/except:
   - Try: call `func(*args, **kwargs)` and return result
   - Except: call `convert_exception_to_envelope(exc, operation, empty_result)` and return envelope
4. Add comprehensive docstring explaining:
   - When to use decorator (all MCP tool functions)
   - Parameters (operation format, empty_result structure)
   - Benefits (automatic error handling, consistent format)
   - Examples with real MCP tool usage
5. Add type annotations using TypeVar for generic function types
6. Test decorator preserves function signatures (important for FastMCP schema generation)

**Acceptance**:
- Decorator catches ALL exceptions
- Function signature preserved (via `@wraps`)
- Error envelope returned (not raised)
- Docstring includes Examples section
- Pyright clean

**Time Estimate**: 2 hours

---

### Task 5: Write Unit Tests for Exception Conversion
**File**: `tests/codeintel_rev/test_error_handling.py` (NEW)

**Description**: Comprehensive unit tests for exception → envelope conversion.

**Subtasks**:
1. Create test fixtures:
   - Mock logger for verifying structured logging
   - Sample empty_result dict
   - Sample operation string
2. Test KgFoundryError conversion:
   - VectorSearchError → Problem Details with correct status/code
   - Verify structured logging with error code
   - Verify context included in envelope
3. Test FileNotFoundError conversion:
   - Maps to 404 status
   - Problem Details type is file-not-found
   - Warning logged
4. Test UnicodeDecodeError conversion:
   - Maps to 415 status
   - Encoding and reason in extensions
   - Warning logged
5. Test ValueError conversion:
   - Maps to 400 status
   - Invalid-parameter type
6. Test unknown exception conversion:
   - Maps to 500 status
   - Exception type in extensions
   - Full stack trace logged (exception level)
7. Test empty_result merging:
   - All empty_result fields present in envelope
   - error and problem fields added
8. Use `@pytest.mark.parametrize` for testing multiple exception types
9. Verify Problem Details structure against schema

**Acceptance**:
- All exception types tested
- Structured logging verified (mock assertions)
- Problem Details structure correct
- Pyright clean
- 100% coverage for `convert_exception_to_envelope()`

**Time Estimate**: 3 hours

---

### Task 6: Write Unit Tests for Decorator
**File**: `tests/codeintel_rev/test_error_handling.py` (continued)

**Description**: Test decorator behavior with various error scenarios.

**Subtasks**:
1. Test success case (no exception):
   - Decorator passes through result unchanged
   - No logging occurs
2. Test exception handling:
   - Decorator catches exception
   - Converts to error envelope
   - Returns envelope (does not raise)
3. Test function signature preservation:
   - Decorated function has same __name__, __doc__, __annotations__
   - Important for FastMCP JSON Schema generation
4. Test with async functions:
   - Decorator works with async def functions
   - await properly handled
5. Test multiple exception types in sequence:
   - Same decorator handles FileNotFoundError, ValueError, etc.
6. Test empty_result parameter variations:
   - Different tool-specific empty results work correctly

**Acceptance**:
- All decorator behaviors tested
- Success and error paths verified
- Signature preservation confirmed
- Async compatibility tested
- Pyright clean

**Time Estimate**: 2 hours

---

### Task 7: Add Error Codes to ErrorCode Enum
**File**: `src/kgfoundry_common/errors/codes.py` (UPDATED if needed)

**Description**: Ensure all needed error codes exist in ErrorCode enum.

**Subtasks**:
1. Check if these codes exist:
   - `FILE_OPERATION_ERROR`
   - `GIT_OPERATION_ERROR`
   - `INVALID_PARAMETER` (may already exist)
2. Add missing codes with HTTP status mapping:
   ```python
   FILE_OPERATION_ERROR = "file-operation-error"
   GIT_OPERATION_ERROR = "git-operation-error"
   ```
3. Update `get_type_uri()` to map new codes to URIs
4. Update documentation/docstrings

**Acceptance**:
- All error codes available
- URI mapping correct
- Documentation updated

**Time Estimate**: 0.5 hours

---

### Task 8: Document Error Handling Architecture
**File**: `codeintel_rev/docs/error_handling_guide.md` (NEW)

**Description**: Create developer guide for error handling patterns.

**Subtasks**:
1. Write overview of three-layer architecture
2. Document when to raise exceptions (in adapters)
3. Document when to use decorator (MCP tool functions)
4. Provide code examples for each exception type
5. Explain error envelope structure
6. Show before/after refactoring examples
7. Document testing patterns for error scenarios
8. Add troubleshooting section

**Acceptance**:
- Guide is comprehensive and clear
- Examples are copy-ready
- All exception types documented
- Testing patterns included

**Time Estimate**: 1.5 hours

---

## Phase 4b: Adapter Refactoring (Week 2)

### Task 9: Refactor open_file Adapter (Exception-Based)
**File**: `codeintel_rev/mcp_server/adapters/files.py`

**Description**: Convert open_file to exception-based error handling.

**Subtasks**:
1. Remove all manual `return {"error": ...}` statements
2. Replace with appropriate exceptions:
   - `PathOutsideRepositoryError` already raised by `resolve_within_repo`
   - Add `raise FileNotFoundError(f"Not a file: {path}")` for is_file() check
   - Wrap UnicodeDecodeError with `FileReadError`
   - Add `raise InvalidLineRangeError(...)` for line validation
3. Update docstring to include Raises section:
   ```python
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
   ```
4. Remove error-related return type hints from function signature
5. Verify function only returns success dict

**Acceptance**:
- Zero manual error dicts (all raised as exceptions)
- Docstring Raises section complete
- Success path returns dict with path, content, lines, size
- Pyright clean
- Function length reduced by 30-40%

**Time Estimate**: 2 hours

---

### Task 10: Add Error Decorator to open_file_tool
**File**: `codeintel_rev/mcp_server/server.py`

**Description**: Wrap open_file MCP tool with error handling decorator.

**Subtasks**:
1. Import decorator:
   ```python
   from codeintel_rev.mcp_server.error_handling import handle_adapter_errors
   ```
2. Add decorator to open_file_tool:
   ```python
   @mcp.tool()
   @handle_adapter_errors(
       operation="files:open_file",
       empty_result={"path": "", "content": "", "lines": 0, "size": 0}
   )
   def open_file(path: str, start_line: int | None, end_line: int | None) -> dict:
   ```
3. Verify decorator is AFTER @mcp.tool() (order matters)
4. Update docstring to mention automatic error handling

**Acceptance**:
- Decorator applied correctly
- Empty result fields match success response
- Operation string follows "category:operation" format
- Pyright clean

**Time Estimate**: 0.5 hours

---

### Task 11: Update open_file Unit Tests
**File**: `tests/codeintel_rev/test_files_adapter.py`

**Description**: Update tests to expect exceptions instead of error dicts.

**Subtasks**:
1. Update tests for PathOutsideRepositoryError:
   ```python
   with pytest.raises(PathOutsideRepositoryError):
       open_file(context, "../../etc/passwd")
   ```
2. Update tests for FileNotFoundError:
   ```python
   with pytest.raises(FileNotFoundError, match="Not a file"):
       open_file(context, "README.md")  # Directory, not file
   ```
3. Update tests for FileReadError:
   ```python
   with pytest.raises(FileReadError, match="encoding error"):
       open_file(context, "binary_file.png")
   ```
4. Update tests for InvalidLineRangeError:
   ```python
   with pytest.raises(InvalidLineRangeError, match="positive integer"):
       open_file(context, "README.md", start_line=0)
   ```
5. Add tests verifying exception context (path, line_range fields)
6. Add tests for MCP tool wrapper (decorator error envelope)

**Acceptance**:
- All tests updated to expect exceptions
- Exception messages verified with `match` parameter
- Exception context verified
- MCP tool wrapper tests added
- All tests pass

**Time Estimate**: 2 hours

---

### Task 12: Refactor list_paths Adapter
**File**: `codeintel_rev/mcp_server/adapters/files.py`

**Description**: Update list_paths error handling (mostly done, minor cleanup).

**Subtasks**:
1. Review current error handling in `_list_paths_sync`:
   - Currently returns `{"items": [], "total": 0, "error": "..."}`
   - Should raise exceptions instead
2. Convert error return to exception:
   ```python
   # Before
   if search_root is None:
       return {"items": [], "total": 0, "error": error or "Path not found"}
   
   # After
   if search_root is None:
       raise FileNotFoundError(error or "Path not found or not a directory")
   ```
3. Update `_resolve_search_root()` to raise instead of return error tuple
4. Update docstring Raises section

**Acceptance**:
- All error paths raise exceptions
- No manual error dicts
- Pyright clean

**Time Estimate**: 1 hour

---

### Task 13: Add Error Decorator to list_paths_tool
**File**: `codeintel_rev/mcp_server/server.py`

**Description**: Wrap list_paths MCP tool with error handling decorator.

**Subtasks**:
1. Add decorator:
   ```python
   @mcp.tool()
   @handle_adapter_errors(
       operation="files:list_paths",
       empty_result={"items": [], "total": 0, "truncated": False}
   )
   async def list_paths(...):
   ```
2. Update docstring

**Acceptance**:
- Decorator applied
- Empty result matches success response
- Pyright clean

**Time Estimate**: 0.5 hours

---

### Task 14: Update list_paths Unit Tests
**File**: `tests/codeintel_rev/test_files_adapter.py`

**Description**: Update tests to expect exceptions.

**Subtasks**:
1. Update path not found tests:
   ```python
   with pytest.raises(FileNotFoundError):
       await list_paths(context, path="nonexistent")
   ```
2. Update tests for path outside repository
3. Add MCP tool wrapper tests

**Acceptance**:
- All tests updated
- Exception types and messages verified
- All tests pass

**Time Estimate**: 1 hour

---

### Task 15: Refactor blame_range Adapter
**File**: `codeintel_rev/mcp_server/adapters/history.py`

**Description**: Convert blame_range to exception-based error handling.

**Subtasks**:
1. Remove all `return {"blame": [], "error": ...}` statements
2. Keep exceptions raised by AsyncGitClient:
   - `FileNotFoundError` already raised
   - `git.exc.GitCommandError` already raised
3. Wrap GitCommandError with GitOperationError for better semantics:
   ```python
   except git.exc.GitCommandError as exc:
       raise GitOperationError(
           "Git blame failed",
           path=relative_path,
           git_command="blame",
       ) from exc
   ```
4. Update docstring Raises section
5. Remove current LOGGER.warning calls (decorator will handle)

**Acceptance**:
- Zero manual error dicts
- Exceptions raised with proper context
- Docstring updated
- Pyright clean

**Time Estimate**: 1.5 hours

---

### Task 16: Add Error Decorator to blame_range_tool
**File**: `codeintel_rev/mcp_server/server.py`

**Description**: Wrap blame_range MCP tool with error handling decorator.

**Subtasks**:
1. Add decorator:
   ```python
   @mcp.tool()
   @handle_adapter_errors(
       operation="git:blame_range",
       empty_result={"blame": []}
   )
   async def blame_range(...):
   ```
2. Update docstring

**Acceptance**:
- Decorator applied
- Empty result correct
- Pyright clean

**Time Estimate**: 0.5 hours

---

### Task 17: Update blame_range Unit Tests
**File**: `tests/codeintel_rev/test_history_adapter.py`

**Description**: Update tests to expect exceptions.

**Subtasks**:
1. Update tests for FileNotFoundError:
   ```python
   with pytest.raises(FileNotFoundError):
       await blame_range(context, "nonexistent.py", 1, 10)
   ```
2. Update tests for GitOperationError:
   ```python
   with pytest.raises(GitOperationError, match="Git blame failed"):
       await blame_range(context, "invalid.py", 1, 10)
   ```
3. Verify exception context includes path and git_command
4. Add MCP tool wrapper tests

**Acceptance**:
- All tests updated
- Exception types and context verified
- All tests pass

**Time Estimate**: 1.5 hours

---

### Task 18: Refactor file_history Adapter
**File**: `codeintel_rev/mcp_server/adapters/history.py`

**Description**: Convert file_history to exception-based error handling.

**Subtasks**:
1. Remove all `return {"commits": [], "error": ...}` statements
2. Wrap GitCommandError with GitOperationError:
   ```python
   except git.exc.GitCommandError as exc:
       raise GitOperationError(
           "Git log failed",
           path=relative_path,
           git_command="log",
       ) from exc
   ```
3. Update docstring Raises section

**Acceptance**:
- Zero manual error dicts
- Exceptions properly wrapped
- Docstring updated
- Pyright clean

**Time Estimate**: 1 hour

---

### Task 19: Add Error Decorator to file_history_tool
**File**: `codeintel_rev/mcp_server/server.py`

**Description**: Wrap file_history MCP tool with error handling decorator.

**Subtasks**:
1. Add decorator:
   ```python
   @mcp.tool()
   @handle_adapter_errors(
       operation="git:file_history",
       empty_result={"commits": []}
   )
   async def file_history(...):
   ```
2. Update docstring

**Acceptance**:
- Decorator applied
- Empty result correct
- Pyright clean

**Time Estimate**: 0.5 hours

---

### Task 20: Update file_history Unit Tests
**File**: `tests/codeintel_rev/test_history_adapter.py`

**Description**: Update tests to expect exceptions.

**Subtasks**:
1. Update tests for FileNotFoundError
2. Update tests for GitOperationError
3. Verify exception context
4. Add MCP tool wrapper tests

**Acceptance**:
- All tests updated
- All tests pass

**Time Estimate**: 1 hour

---

### Task 21: Standardize text_search Error Envelope
**File**: `codeintel_rev/mcp_server/adapters/text_search.py`

**Description**: Update text_search to use unified error handling (remove custom _error_response).

**Subtasks**:
1. Remove `_error_response()` helper function (lines 352-381)
2. Update `search_text()` to raise exceptions instead of returning error dicts:
   ```python
   # Before
   except SubprocessTimeoutError:
       return _error_response(VectorSearchError("Search timeout", ...), operation="text_search")
   
   # After
   except SubprocessTimeoutError:
       raise VectorSearchError("Search timeout", context={"query": query})
   ```
3. Keep VectorSearchError for search failures
4. Update docstring Raises section
5. Remove manual error dict construction for fallback_grep too

**Acceptance**:
- `_error_response()` function removed
- All error paths raise exceptions
- Docstring updated
- 30+ lines of code removed

**Time Estimate**: 2 hours

---

### Task 22: Add Error Decorator to search_text_tool
**File**: `codeintel_rev/mcp_server/server.py`

**Description**: Wrap search_text MCP tool with error handling decorator.

**Subtasks**:
1. Add decorator:
   ```python
   @mcp.tool()
   @handle_adapter_errors(
       operation="search:text",
       empty_result={"matches": [], "total": 0, "truncated": False}
   )
   def search_text(...):
   ```
2. Verify decorator works with non-async function
3. Update docstring

**Acceptance**:
- Decorator applied
- Empty result correct
- Pyright clean

**Time Estimate**: 0.5 hours

---

### Task 23: Update text_search Unit Tests
**File**: `tests/codeintel_rev/test_text_search_adapter.py`

**Description**: Update tests to expect exceptions.

**Subtasks**:
1. Update timeout tests:
   ```python
   with pytest.raises(VectorSearchError, match="timeout"):
       search_text(context, "query")
   ```
2. Update subprocess error tests
3. Verify exception context
4. Add MCP tool wrapper tests

**Acceptance**:
- All tests updated
- All tests pass

**Time Estimate**: 1.5 hours

---

### Task 24: Standardize semantic_search Error Envelope
**File**: `codeintel_rev/mcp_server/adapters/semantic.py`

**Description**: Update semantic_search to use unified error handling (remove custom _error_envelope).

**Subtasks**:
1. Remove `_error_envelope()` helper function (lines 480-521)
2. Update `_semantic_search_sync()` to raise exceptions:
   ```python
   # Before
   if not ready:
       return _error_envelope(VectorSearchError(...), limits=...)
   
   # After
   if not ready:
       raise VectorSearchError(faiss_error or "Index not available", context={"faiss_index": ...})
   ```
3. Raise EmbeddingError for embedding failures
4. Raise VectorSearchError for FAISS failures
5. Update docstring Raises section
6. Keep success case returning AnswerEnvelope

**Acceptance**:
- `_error_envelope()` function removed
- All error paths raise exceptions
- Success path unchanged (returns AnswerEnvelope)
- 40+ lines of code removed

**Time Estimate**: 2.5 hours

---

### Task 25: Add Error Decorator to semantic_search_tool
**File**: `codeintel_rev/mcp_server/server.py`

**Description**: Wrap semantic_search MCP tool with error handling decorator.

**Subtasks**:
1. Add decorator:
   ```python
   @mcp.tool()
   @handle_adapter_errors(
       operation="search:semantic",
       empty_result={"findings": [], "answer": "", "confidence": 0.0}
   )
   async def semantic_search(...):
   ```
2. Note: AnswerEnvelope has many optional fields; decorator adds error + problem to this envelope
3. Update docstring

**Acceptance**:
- Decorator applied
- Empty result includes core AnswerEnvelope fields
- Pyright clean

**Time Estimate**: 0.5 hours

---

### Task 26: Update semantic_search Unit Tests
**File**: `tests/codeintel_rev/test_semantic_adapter.py`

**Description**: Update tests to expect exceptions.

**Subtasks**:
1. Update FAISS not ready tests:
   ```python
   with pytest.raises(VectorSearchError, match="Index not available"):
       await semantic_search(context, "query")
   ```
2. Update embedding error tests
3. Update FAISS search error tests
4. Verify exception context
5. Add MCP tool wrapper tests
6. Verify success case still returns AnswerEnvelope

**Acceptance**:
- All tests updated
- Exception types verified
- Success case unchanged
- All tests pass

**Time Estimate**: 2 hours

---

## Phase 4c: Testing & Documentation (Week 2)

### Task 27: Write Error Scenario Integration Tests
**File**: `tests/codeintel_rev/integration/test_error_scenarios.py` (NEW)

**Description**: End-to-end tests for error handling across all adapters.

**Subtasks**:
1. Create test fixtures:
   - ApplicationContext with real config
   - Test repository with various files
2. Test file not found scenario:
   - Call open_file with nonexistent path
   - Verify error envelope structure
   - Verify Problem Details fields
   - Verify error code and HTTP status
3. Test invalid line range scenario:
   - Call open_file with negative line numbers
   - Verify InvalidLineRangeError mapped to Problem Details
4. Test Git operation failure:
   - Call blame_range on invalid file
   - Verify GitOperationError handling
5. Test encoding error:
   - Call open_file on binary file
   - Verify UnicodeDecodeError → FileReadError → 415 status
6. Test search timeout:
   - Mock ripgrep timeout
   - Verify VectorSearchError handling
7. Test FAISS not ready:
   - Mock FAISS unavailable
   - Verify VectorSearchError handling
8. Test unknown exception:
   - Inject unexpected exception
   - Verify 500 Internal Error response
9. Use `@pytest.mark.integration` marker

**Acceptance**:
- All error scenarios tested end-to-end
- Problem Details structure verified
- HTTP status codes correct
- Error codes correct
- All tests pass

**Time Estimate**: 3 hours

---

### Task 28: Write Problem Details Validation Tests
**File**: `tests/codeintel_rev/test_problem_details_validation.py` (NEW)

**Description**: Verify all Problem Details payloads validate against RFC 9457 schema.

**Subtasks**:
1. Load canonical Problem Details schema from `schema/common/problem_details.json`
2. Create test cases for each exception type:
   - Generate Problem Details via `convert_exception_to_envelope()`
   - Validate against schema using `jsonschema.validate()`
3. Test required fields present:
   - type, title, status, detail, instance
4. Test optional fields:
   - code, extensions
5. Test type URIs follow format:
   - `https://kgfoundry.dev/problems/{code}`
6. Test status codes match HTTP semantics:
   - 4xx for client errors
   - 5xx for server errors
7. Use `@pytest.mark.parametrize` for multiple exception types

**Acceptance**:
- All Problem Details validate against schema
- Required fields present
- Type URIs correct format
- Status codes appropriate
- All tests pass

**Time Estimate**: 2 hours

---

### Task 29: Write Structured Logging Verification Tests
**File**: `tests/codeintel_rev/test_error_logging.py` (NEW)

**Description**: Verify all errors logged with structured context.

**Subtasks**:
1. Create mock logger with caplog fixture
2. Test KgFoundryError logging:
   - Verify `with_fields()` used
   - Verify operation, error_code in extra fields
   - Verify log level matches exception severity
3. Test FileNotFoundError logging:
   - Verify WARNING level
   - Verify operation in extra fields
4. Test unknown exception logging:
   - Verify EXCEPTION level (includes stack trace)
   - Verify exception_type in extra fields
5. Test log message format:
   - Human-readable message
   - No sensitive data (paths sanitized if needed)
6. Use caplog fixture to capture log records:
   ```python
   with caplog.at_level(logging.WARNING):
       convert_exception_to_envelope(exc, ...)
       assert "File not found" in caplog.text
       assert caplog.records[0].operation == "files:open_file"
   ```

**Acceptance**:
- All exception types have logging tests
- Structured fields verified
- Log levels appropriate
- No sensitive data leaked
- All tests pass

**Time Estimate**: 2 hours

---

### Task 30: Update Adapter Documentation
**File**: `codeintel_rev/README.md` (UPDATED)

**Description**: Document error handling patterns for developers.

**Subtasks**:
1. Add "Error Handling" section to README
2. Explain three-layer architecture briefly
3. Link to detailed guide (`docs/error_handling_guide.md`)
4. Provide quick examples:
   - Raising exceptions in adapters
   - Using decorator in MCP tools
   - Error envelope structure
5. Document breaking changes (if any):
   - Adapter functions now raise exceptions (internal change)
   - Client-facing responses unchanged (backward compatible)

**Acceptance**:
- README has error handling section
- Examples are clear
- Links to detailed guide
- Breaking changes documented (if any)

**Time Estimate**: 1 hour

---

### Task 31: Create Error Handling Developer Guide
**File**: `codeintel_rev/docs/error_handling_guide.md` (NEW - if not done in Task 8)

**Description**: Comprehensive guide for developers implementing error handling.

**Subtasks**:
1. Architecture overview with diagrams
2. When to raise exceptions (adapter layer)
3. When to use decorator (MCP tool layer)
4. Available exception types:
   - FileOperationError hierarchy
   - GitOperationError
   - VectorSearchError
   - EmbeddingError
5. Problem Details mapping:
   - Exception type → HTTP status
   - Exception type → error code
   - Context → extensions
6. Testing patterns:
   - How to test exception raising
   - How to test error envelopes
   - How to test logging
7. Common pitfalls:
   - Don't return error dicts from adapters
   - Don't catch exceptions in adapters (let decorator handle)
   - Don't forget empty_result in decorator
8. Before/after refactoring examples
9. Troubleshooting section

**Acceptance**:
- Guide is comprehensive (10+ sections)
- Examples are copy-ready
- All exception types documented
- Testing patterns clear
- Troubleshooting covers common issues

**Time Estimate**: 2 hours

---

### Task 32: Run Full Test Suite and Verify Coverage
**File**: N/A (CI/local testing)

**Description**: Ensure all tests pass and coverage is adequate.

**Subtasks**:
1. Run unit tests:
   ```bash
   uv run pytest tests/codeintel_rev/test_error_handling.py -v
   uv run pytest tests/codeintel_rev/test_*_adapter.py -v
   ```
2. Run integration tests:
   ```bash
   uv run pytest tests/codeintel_rev/integration/test_error_scenarios.py -v
   ```
3. Run coverage:
   ```bash
   uv run pytest --cov=codeintel_rev/mcp_server/error_handling --cov-report=term-missing
   uv run pytest --cov=codeintel_rev/errors --cov-report=term-missing
   ```
4. Verify coverage targets:
   - `error_handling.py`: 100% coverage
   - `errors.py`: 100% coverage
   - Adapters error paths: 90%+ coverage
5. Fix any failing tests
6. Add missing test cases for uncovered branches

**Acceptance**:
- All unit tests pass
- All integration tests pass
- Coverage ≥90% for error handling code
- No flaky tests

**Time Estimate**: 1 hour

---

### Task 33: Update OpenAPI/MCP Schemas (if applicable)
**File**: `openapi/*.yaml` (if exists)

**Description**: Update OpenAPI schemas to reflect error response structure.

**Subtasks**:
1. Check if OpenAPI schemas exist for MCP tools
2. Update response schemas to include error and problem fields:
   ```yaml
   responses:
     200:
       description: Success or error
       content:
         application/json:
           schema:
             oneOf:
               - $ref: '#/components/schemas/OpenFileSuccess'
               - $ref: '#/components/schemas/OpenFileError'
   ```
3. Define ProblemDetails schema component
4. Link to RFC 9457 in documentation
5. Validate schemas with OpenAPI linter

**Acceptance**:
- OpenAPI schemas updated (if applicable)
- Error responses documented
- Schemas validate

**Time Estimate**: 1 hour (or 0 if no OpenAPI schemas)

---

## Summary

**Total Tasks**: 33  
**Total Estimated Time**: 50 hours (2 weeks at 25 hours/week)

**Task Breakdown by Phase**:
- Phase 4a (Infrastructure): 8 tasks, 15 hours
- Phase 4b (Refactoring): 18 tasks, 25 hours
- Phase 4c (Testing/Docs): 7 tasks, 10 hours

**Critical Path**:
- Tasks 1-4 must complete before adapter refactoring (error infrastructure)
- Adapter refactoring can proceed in parallel (files, history, search)
- Testing/docs in parallel with later adapter work

**Dependencies**:
- Phases 1-3 complete (ApplicationContext, GitClient, scope management)
- `kgfoundry_common.errors` available
- `kgfoundry_common.problem_details` available
- All adapters using ApplicationContext (Phase 1)

**Code Metrics (Expected After Completion)**:

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Total error handling lines | 280+ | 150 | **-46%** |
| Duplicated code lines | 150+ | 0 | **-100%** |
| Manual error dict sites | 23 | 0 | **-100%** |
| Problem Details coverage | 50% (2/4 adapters) | 100% (4/4) | **+100%** |
| Structured logging coverage | 50% | 100% | **+100%** |

