# Phase 4: Consistent Error Handling and Responses

**Openspec Change Proposal**  
**Status**: Ready for Implementation  
**Version**: 1.0.0  
**Duration**: 2 weeks (50 hours)

## Executive Summary

This proposal standardizes error handling across all CodeIntel MCP adapters, eliminating **3 different error formats**, **150+ lines of duplicated code**, and **23 manual error construction sites**. By adopting a **three-layer exception-based architecture**, we achieve:

- ✅ **46% code reduction** in error handling (280+ lines → 150 lines)
- ✅ **100% RFC 9457 compliance** (up from 50%)
- ✅ **100% structured logging coverage** (up from 50%)
- ✅ **Zero manual error dicts** (down from 23 sites)
- ✅ **Uniform client experience** (1 error format vs 3)

### The Problem (Current State)

**Inconsistent Error Formats**:
- `text_search`: `{"matches": [], "error": "...", "problem": {...}}`
- `semantic_search`: `AnswerEnvelope` with embedded `problem`
- `files` + `history`: `{"error": "...", "path": "..."}` (no Problem Details)

**Duplicated Logic**:
- `_error_response()` in text_search (30 lines)
- `_error_envelope()` in semantic (42 lines)
- Inline error dicts in files/history (80+ lines)

**Impact**: Clients must handle 3 formats, no uniform error codes/HTTP status, observability gaps.

### The Solution (Three-Layer Architecture)

```
Adapter (raise exception) → Decorator (convert) → Client (uniform envelope)
```

**Layer 1**: Adapters raise typed exceptions (no manual error dicts)  
**Layer 2**: Decorator catches all, converts to Problem Details, logs  
**Layer 3**: Clients receive uniform error envelope

### Key Improvements

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Error formats | 3 | 1 | **-67%** |
| Duplicated code | 150+ lines | 0 | **-100%** |
| Manual error sites | 23 | 0 | **-100%** |
| Problem Details coverage | 50% | 100% | **+100%** |
| Structured logging | 50% | 100% | **+100%** |
| Adapter error handling lines | 280+ | 150 | **-46%** |

---

## Documentation Map

This proposal includes 6 comprehensive documents:

### 📋 1. [proposal.md](./proposal.md) (130 lines)
High-level proposal with problem statement, solution architecture, success criteria, and migration path.

**Key Sections**:
- Problem Statement (3 error formats, duplicated code)
- Three-Layer Architecture diagram
- Success Criteria (5 metrics)
- Migration Path (3 phases)

**Read this first** for executive context.

---

### 🏗️ 2. [design.md](./design.md) (930+ lines) ⭐
**Most comprehensive document.** Complete architectural design with 4 patterns, before/after code examples, and implementation details.

**Key Sections**:
- Architecture: Three-Layer Error Handling (with ASCII diagrams)
- Design Pattern 1: Unified Error Envelope (before/after code)
- Design Pattern 2: Exception-Based Adapters (81 lines → 61 lines example)
- Design Pattern 3: Centralized Exception Conversion (complete implementation)
- Design Pattern 4: Domain-Specific Exceptions (typed hierarchy)
- Migration Strategy (3 phases)
- Complete `open_file` refactor example (67% code reduction)

**Read this** for deep architectural understanding and implementation patterns.

---

### ✅ 3. [tasks.md](./tasks.md) (33 tasks, 800+ lines)
Exhaustive task breakdown with subtasks, acceptance criteria, and time estimates.

**Phase Breakdown**:
- **Phase 4a** (Week 1): 8 tasks, 15 hours - Error infrastructure
- **Phase 4b** (Week 2): 18 tasks, 25 hours - Adapter refactoring
- **Phase 4c** (Week 2): 7 tasks, 10 hours - Testing & documentation

**Each task includes**:
- Detailed subtasks
- Code examples
- Acceptance criteria
- Time estimate

**Use this** as implementation guide (task-by-task checklist).

---

### 📐 4. [specs/codeintel-error-envelope/spec.md](./specs/codeintel-error-envelope/spec.md) (900+ lines)
Formal capability specification with 15 functional requirements, data contracts, observability metrics, and testing strategy.

**Key Sections**:
- 15 Functional Requirements (FR-ERR-001 through FR-ERR-015)
  - FR-ERR-001: Unified Error Envelope Structure
  - FR-ERR-002: RFC 9457 Problem Details Compliance
  - FR-ERR-003: Exception-Based Adapter Implementation
  - FR-ERR-004: Automatic Exception Conversion
  - FR-ERR-005: Domain Exception Hierarchy
  - ...and 10 more
- Data Contracts (error envelope structure, exception mappings, context fields)
- Observability (metrics, logs, tracing)
- Testing Strategy (unit, integration, load tests)
- Examples (success/error responses for each adapter)

**Use this** for formal requirements and acceptance testing.

---

### 💻 5. [implementation/](./implementation/) (3 files, 500+ lines)
Reference implementations with production-ready code and comprehensive NumPy docstrings.

**Files**:
- **error_handling.py** (250 lines): `convert_exception_to_envelope()` and `@handle_adapter_errors` decorator
- **errors.py** (250 lines): Domain exception hierarchy (FileOperationError, GitOperationError, etc.)

**Each file includes**:
- Module-level docstring with architecture overview
- Function/class docstrings with Parameters, Returns, Notes, Examples
- Type annotations (pyright strict compliant)
- Example usage in docstrings

**Use this** as copy-ready implementation reference.

---

### 📖 6. [README.md](./README.md) (this file)
Executive overview and navigation guide to all documents.

---

## Quick Start (For Implementers)

### Step 1: Read Architecture (15 minutes)
Read [design.md](./design.md) sections:
- "Architecture: Three-Layer Error Handling"
- "Design Pattern 2: Exception-Based Adapters"
- "Design Pattern 3: Centralized Exception Conversion"

### Step 2: Review Reference Implementation (10 minutes)
Open [implementation/error_handling.py](./implementation/error_handling.py) and review:
- `convert_exception_to_envelope()` function
- `@handle_adapter_errors` decorator
- Module docstring with examples

### Step 3: Follow Task Checklist (2 weeks)
Use [tasks.md](./tasks.md) as implementation guide:
- Week 1: Tasks 1-8 (error infrastructure)
- Week 2: Tasks 9-26 (adapter refactoring)
- Week 2: Tasks 27-33 (testing & docs)

### Step 4: Verify Requirements (Final)
Use [specs/codeintel-error-envelope/spec.md](./specs/codeintel-error-envelope/spec.md) for acceptance testing:
- FR-ERR-001 through FR-ERR-015
- Run all verification steps
- Validate against data contracts

---

## Before & After Examples

### Example 1: open_file (Files Adapter)

**Before** (81 lines, 45 error handling, 7 manual error dicts):

```python
def open_file(context, path, start_line, end_line):
    # Error path 1: Path validation
    try:
        file_path = resolve_within_repo(repo_root, path)
    except PathOutsideRepositoryError as exc:
        return {"error": str(exc), "path": path}  # Manual dict
    except FileNotFoundError:
        return {"error": "File not found", "path": path}  # Manual dict
    
    # Error path 2: File type check
    if not file_path.is_file():
        return {"error": "Not a file", "path": path}  # Manual dict
    
    # Error path 3: Encoding
    try:
        content = file_path.read_text()
    except UnicodeDecodeError:
        return {"error": "Binary file", "path": path}  # Manual dict
    
    # Error paths 4-6: Line validation
    if start_line <= 0:
        return {"error": "start_line must be positive", "path": path}
    # ... 3 more manual error dicts ...
    
    # Success path
    return {"path": path, "content": content, ...}
```

**After** (51 lines, 15 error handling, 0 manual error dicts):

```python
def open_file(context, path, start_line, end_line):
    """Read file content.
    
    Raises
    ------
    PathOutsideRepositoryError, FileNotFoundError,
    FileReadError, InvalidLineRangeError
    """
    # Path validation (raises on error)
    file_path = resolve_within_repo(repo_root, path)
    
    # File type check
    if not file_path.is_file():
        raise FileNotFoundError(f"Not a file: {path}")
    
    # Read content
    try:
        content = file_path.read_text()
    except UnicodeDecodeError as exc:
        raise FileReadError("Binary file", path=path) from exc
    
    # Line validation
    if start_line <= 0:
        raise InvalidLineRangeError(
            "start_line must be positive",
            path=path,
            line_range=(start_line, end_line)
        )
    # ... raise other exceptions ...
    
    # Success path
    return {"path": path, "content": content, ...}
```

**MCP Tool Wrapper** (decorator handles errors):

```python
@mcp.tool()
@handle_adapter_errors(
    operation="files:open_file",
    empty_result={"path": "", "content": "", "lines": 0, "size": 0}
)
def open_file_tool(path, start_line, end_line):
    context = get_context()
    return open_file(context, path, start_line, end_line)
```

**Metrics**:
- Total lines: **81 → 61** (-25%)
- Error handling lines: **45 → 15** (-67%)
- Manual error dicts: **7 → 0** (-100%)
- Problem Details: **❌ → ✅** (automatic)
- Structured logging: **❌ → ✅** (automatic)

---

### Example 2: Error Response (Client-Facing)

**Before** (files.py - no Problem Details):

```json
{
    "error": "File not found",
    "path": "src/main.py"
}
```

**Before** (text_search.py - Problem Details present):

```json
{
    "matches": [],
    "total": 0,
    "error": "Search timeout",
    "problem": {
        "type": "https://kgfoundry.dev/problems/vector-search-error",
        "status": 503,
        "detail": "Search timeout"
    }
}
```

**Before** (semantic.py - AnswerEnvelope):

```json
{
    "findings": [],
    "answer": "Index not available",
    "confidence": 0.0,
    "problem": {...}
}
```

**After** (all adapters - uniform structure):

```json
{
    "path": "",              // Tool-specific fields (empty on error)
    "content": "",
    "lines": 0,
    "size": 0,
    "error": "File not found: src/main.py",  // Human-readable
    "problem": {             // RFC 9457 Problem Details
        "type": "https://kgfoundry.dev/problems/file-not-found",
        "title": "File Not Found",
        "status": 404,
        "detail": "File not found: src/main.py",
        "instance": "urn:codeintel:files:open_file",
        "code": "file-not-found"
    }
}
```

**Benefits**:
- ✅ Same structure across all tools
- ✅ RFC 9457 compliant (100%)
- ✅ HTTP status code included
- ✅ Error code for programmatic handling
- ✅ Tool-specific fields present (just empty)

---

## Key Architectural Decisions

### Decision 1: Exception-Based vs Return-Based

**Chosen**: Exception-based (adapters raise, decorator catches)

**Rationale**:
- **Separation of concerns**: Adapters focus on domain logic
- **DRY**: Single conversion point (decorator) vs duplicated error dicts
- **EAFP**: Pythonic error handling style
- **Testability**: Assert exceptions vs parsing error dicts
- **Code reduction**: 40-50% fewer lines

**Alternative**: Return-based (adapters return error dicts)
- **Rejected**: Duplicates error formatting, hard to ensure consistency

---

### Decision 2: Single Decorator vs Multiple Helpers

**Chosen**: Single `@handle_adapter_errors` decorator

**Rationale**:
- **Consistency**: All tools use same decorator
- **Simplicity**: One pattern to learn
- **Maintainability**: Change once, affects all
- **Type safety**: Decorator preserves signatures

**Alternative**: Tool-specific helpers (`_error_response_for_files`, etc.)
- **Rejected**: Duplicates logic, harder to change

---

### Decision 3: Unified Envelope vs Tool-Specific Formats

**Chosen**: Unified envelope (base fields + tool fields)

**Rationale**:
- **Client simplicity**: Check same fields across tools
- **Backward compatible**: Tool fields always present
- **RFC 9457 compliant**: Standard error format
- **Type-safe**: TypedDict enforces structure

**Alternative**: Each tool has different error structure
- **Rejected**: Confuses clients, hard to maintain

---

### Decision 4: Domain Exceptions vs Generic Exceptions

**Chosen**: Domain-specific (FileOperationError, GitOperationError, etc.)

**Rationale**:
- **Semantics**: Exception type conveys meaning
- **Context**: Structured fields (path, line_range, git_command)
- **Automatic mapping**: HTTP status, error codes via exception type
- **Type safety**: Can't forget required context fields

**Alternative**: Generic exceptions (ValueError, RuntimeError)
- **Rejected**: Loses semantic information, no automatic context

---

## Migration Safety

### Backward Compatibility

✅ **No Breaking Changes**:
- Tool-specific result fields always present (empty on error)
- `error` field already exists in most responses
- `problem` field is additive (new field)
- Success response structure unchanged

✅ **Client Compatibility**:
- Existing clients continue to work
- Clients can optionally read `problem` field for structured errors
- No client code changes required

### Rollout Plan

**Week 1**: Deploy infrastructure (no adapter changes)
- Exception hierarchy
- Error handling decorator
- Exception conversion logic

**Week 2**: Refactor adapters one-by-one
- files.py (open_file, list_paths)
- history.py (blame_range, file_history)
- text_search.py (search_text)
- semantic.py (semantic_search)

**Verification**: Integration tests confirm backward compatibility

---

## Testing Strategy

### Unit Tests (15 test files, 200+ tests)

**Exception Conversion** (`test_error_handling.py`):
- Each exception type → Problem Details
- HTTP status codes
- Error codes
- Context in extensions
- Structured logging

**Decorator** (`test_error_handling.py`):
- Success path (no exception)
- Exception handling (all types)
- Signature preservation
- Async compatibility
- Empty result merging

**Adapters** (`test_*_adapter.py`):
- Exception raising (not error dicts)
- Exception context verification
- MCP tool wrapper error envelopes

### Integration Tests (test_error_scenarios.py)

**Error Scenarios**:
- File not found
- Invalid line range
- Git operation failure
- Encoding error
- Search timeout
- FAISS not ready
- Unknown exception

**Verification**:
- Error envelope structure
- Problem Details fields
- HTTP status codes
- Error codes
- Backward compatibility

### Schema Validation Tests

**Problem Details** (`test_problem_details_validation.py`):
- Validate against RFC 9457 schema
- Required fields present
- Type URIs correct format
- Status codes appropriate

---

## Observability

### Metrics

**Counter**: `codeintel_errors_total{error_code, operation, http_status}`  
Monitor: Spike detection (rate change >2x)

**Histogram**: `codeintel_error_handling_duration_seconds{operation}`  
Target: p95 <0.01s

### Logs

All errors logged with structured context:

```json
{
    "level": "WARNING",
    "message": "File not found",
    "component": "codeintel_mcp",
    "operation": "files:open_file",
    "error": "File not found: src/main.py"
}
```

KgFoundryError includes error_code:

```json
{
    "level": "ERROR",
    "message": "Search timeout",
    "component": "codeintel_mcp",
    "operation": "search:text",
    "error_code": "vector-search-error",
    "context": {"query": "def main"}
}
```

---

## FAQ

### Q: Why not use FastAPI exception handlers?

**A**: FastMCP doesn't expose FastAPI's exception handler mechanism. We handle errors at the adapter layer (MCP tool decorator) instead of FastAPI layer.

### Q: What about partial results with warnings?

**A**: Future enhancement. This proposal focuses on error-only responses. Partial results (findings + warnings) will be addressed in future capability.

### Q: How does this affect performance?

**A**: Negligible impact. Exception handling only on error paths (not hot paths). Typical overhead: 1-2ms per error.

### Q: What about existing error-handling code?

**A**: Removed during refactoring. `_error_response()` and `_error_envelope()` helpers deleted. Manual error dicts eliminated.

### Q: Can clients distinguish error types programmatically?

**A**: Yes! Use `problem.code` field (e.g., "file-not-found", "invalid-parameter"). All error codes documented in spec.

### Q: What if an unexpected exception occurs?

**A**: Decorator catches ALL exceptions. Unknown exceptions map to 500 Internal Error with safe message (no stack traces to client).

### Q: How do I test adapter exceptions?

**A**: Use `pytest.raises`:

```python
with pytest.raises(FileNotFoundError):
    open_file(context, "nonexistent.py")
```

For MCP tool wrappers, assert error envelope structure.

---

## Dependencies

**Required**:
- Phase 1 complete: ApplicationContext in all adapters
- Phase 3 complete: GitClient/AsyncGitClient available
- `kgfoundry_common.errors`: Base exception hierarchy
- `kgfoundry_common.problem_details`: Problem Details helpers
- `kgfoundry_common.logging`: Structured logging

**Optional**: None

---

## Timeline & Effort

**Duration**: 2 weeks (50 hours)

**Week 1** (15 hours):
- Error infrastructure (exceptions, decorator, conversion)
- Unit tests
- Documentation

**Week 2** (35 hours):
- Adapter refactoring (4 adapters × 4-7 hours each)
- Integration tests
- Schema validation tests
- Final documentation

**Critical Path**:
- Error infrastructure must complete before adapter refactoring
- Adapters can be refactored in parallel (files, history, search)

---

## Success Metrics (Post-Implementation)

✅ **Code Quality**:
- Error handling lines: 280+ → 150 (-46%)
- Duplicated code: 150+ lines → 0 (-100%)
- Manual error dicts: 23 → 0 (-100%)

✅ **Standards Compliance**:
- RFC 9457 Problem Details: 50% → 100%
- Structured logging: 50% → 100%
- Consistent error format: 3 formats → 1

✅ **Testing**:
- Unit test coverage: ≥90% (error handling code)
- Integration tests: All error scenarios
- Schema validation: All Problem Details

✅ **Observability**:
- All errors logged with structured context
- Error codes in all responses
- HTTP status codes in all responses

---

## References

**RFC 9457**: Problem Details for HTTP APIs  
https://www.rfc-editor.org/rfc/rfc9457.html

**kgfoundry_common.errors**: Exception hierarchy  
`src/kgfoundry_common/errors/`

**kgfoundry_common.problem_details**: Problem Details helpers  
`src/kgfoundry_common/problem_details.py`

**AGENTS.md**: Codebase standards  
`/home/paul/kgfoundry/AGENTS.md`

---

## Document Metadata

**Created**: 2025-11-08  
**Version**: 1.0.0  
**Total Lines**: All documents combined: 3,500+ lines  
**Code Examples**: 50+ before/after examples  
**Task Count**: 33 implementation tasks  
**Estimated Duration**: 2 weeks (50 hours)

