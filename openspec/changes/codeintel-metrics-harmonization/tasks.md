## Phase 1: Common Observability Module Foundation

**Duration**: 1 day  
**Risk**: Low  
**Rollback**: Yes (no existing code touched)

### 1.1 Create Common Module Structure

- [ ] Create `codeintel_rev/mcp_server/common/` directory
- [ ] Add `codeintel_rev/mcp_server/common/__init__.py` (empty, marks package)
- [ ] Verify directory structure with `ls -la codeintel_rev/mcp_server/common/`

### 1.2 Implement Shared Observability Helper

- [ ] Create `codeintel_rev/mcp_server/common/observability.py` with:
  - [ ] `_supports_histogram_labels()` function (copied from adapters, tested)
  - [ ] `_NoopObservation` class (minimal interface: mark_error, mark_success)
  - [ ] `observe_duration()` context manager (wraps kgfoundry_common.observability)
  - [ ] Full NumPy-style docstrings with examples
  - [ ] TYPE_CHECKING imports for optional dependencies
  - [ ] `__all__ = ["observe_duration"]` export

**Code Reference** (see implementation/ for full code)

### 1.3 Add Unit Tests

- [ ] Create `tests/codeintel_rev/test_observability_common.py`
  - [ ] Test `observe_duration` with real MetricsProvider
  - [ ] Test `observe_duration` with disabled metrics (noop fallback)
  - [ ] Test `mark_success()` and `mark_error()` behavior
  - [ ] Test exception handling inside context manager
  - [ ] Test integration with kgfoundry_common.observability

### 1.4 Validation

- [ ] Run `uv run ruff format codeintel_rev/mcp_server/common/`
- [ ] Run `uv run ruff check --fix codeintel_rev/mcp_server/common/`
- [ ] Run `uv run pyright codeintel_rev/mcp_server/common/`
- [ ] Run `uv run pyrefly check codeintel_rev/mcp_server/common/`
- [ ] Run `SKIP_GPU_WARMUP=1 uv run pytest tests/codeintel_rev/test_observability_common.py -v`
- [ ] Verify 95%+ coverage: `pytest --cov=codeintel_rev.mcp_server.common tests/codeintel_rev/test_observability_common.py`

**Success Criteria**:
- ✅ All quality gates pass (Ruff, pyright, pyrefly)
- ✅ Tests pass with 95%+ coverage
- ✅ No existing code broken (only new files added)

---

## Phase 2: Adapter Refactoring (text_search → semantic)

**Duration**: 2 days  
**Risk**: Low  
**Rollback**: Yes (per-adapter revert)

### 2.1 Refactor text_search Adapter

- [ ] Backup original: `cp codeintel_rev/mcp_server/adapters/text_search.py codeintel_rev/mcp_server/adapters/text_search.py.bak`
- [ ] **Remove local boilerplate** (lines 39-85):
  - [ ] Remove `_supports_histogram_labels()` function
  - [ ] Remove `_METRICS_ENABLED` module variable
  - [ ] Remove `_NoopObservation` class
  - [ ] Remove `_observe()` context manager
- [ ] **Add import**: `from codeintel_rev.mcp_server.common.observability import observe_duration`
- [ ] **Update usage** in `search_text()` (line 215):
  - [ ] Change `with _observe("text_search")` to `with observe_duration("text_search", COMPONENT_NAME)`
- [ ] **Update usage** in `_fallback_grep()` (line 262):
  - [ ] Pass `observation` parameter through (no change needed, already receives it)

### 2.2 Update text_search Tests

- [ ] Run existing tests: `pytest tests/codeintel_rev/test_text_search_adapter.py -v`
- [ ] Verify metrics still emitted (add assertion if missing)
- [ ] Add test verifying `observe_duration` called with correct parameters
- [ ] Check structured logs include operation/component fields

### 2.3 Validation (text_search)

- [ ] Run `uv run ruff format codeintel_rev/mcp_server/adapters/text_search.py`
- [ ] Run `uv run ruff check --fix codeintel_rev/mcp_server/adapters/text_search.py`
- [ ] Run `uv run pyright codeintel_rev/mcp_server/adapters/text_search.py`
- [ ] Run `uv run pyrefly check codeintel_rev/mcp_server/adapters/text_search.py`
- [ ] Run `SKIP_GPU_WARMUP=1 uv run pytest tests/codeintel_rev/test_text_search_adapter.py -v`
- [ ] Manual test: Start server, perform text search, verify metrics in `/metrics` endpoint

**Success Criteria** (text_search):
- ✅ 30+ lines removed (boilerplate elimination)
- ✅ All tests pass
- ✅ Metrics identical to before (same names, labels, values)
- ✅ No Ruff/pyright/pyrefly errors

### 2.4 Refactor semantic Adapter

- [ ] Backup original: `cp codeintel_rev/mcp_server/adapters/semantic.py codeintel_rev/mcp_server/adapters/semantic.py.bak`
- [ ] **Remove local boilerplate** (lines 37-83):
  - [ ] Remove `_supports_histogram_labels()` function
  - [ ] Remove `_METRICS_ENABLED` module variable
  - [ ] Remove `_NoopObservation` class
  - [ ] Remove `_observe()` context manager
- [ ] **Add import**: `from codeintel_rev.mcp_server.common.observability import observe_duration`
- [ ] **Update usage** in `_semantic_search_sync()` (line 151):
  - [ ] Change `with _observe("semantic_search")` to `with observe_duration("semantic_search", COMPONENT_NAME)`

### 2.5 Update semantic Tests

- [ ] Run existing tests: `pytest tests/codeintel_rev/test_semantic_adapter.py -v`
- [ ] Verify metrics still emitted (add assertion if missing)
- [ ] Add test verifying `observe_duration` called with correct parameters
- [ ] Check structured logs include operation/component fields

### 2.6 Validation (semantic)

- [ ] Run `uv run ruff format codeintel_rev/mcp_server/adapters/semantic.py`
- [ ] Run `uv run ruff check --fix codeintel_rev/mcp_server/adapters/semantic.py`
- [ ] Run `uv run pyright codeintel_rev/mcp_server/adapters/semantic.py`
- [ ] Run `uv run pyrefly check codeintel_rev/mcp_server/adapters/semantic.py`
- [ ] Run `SKIP_GPU_WARMUP=1 uv run pytest tests/codeintel_rev/test_semantic_adapter.py -v`
- [ ] Manual test: Start server, perform semantic search, verify metrics in `/metrics` endpoint

**Success Criteria** (semantic):
- ✅ 30+ lines removed (boilerplate elimination)
- ✅ All tests pass
- ✅ Metrics identical to before (same names, labels, values)
- ✅ No Ruff/pyright/pyrefly errors

### 2.7 Full Integration Verification

- [ ] Run full codeintel test suite: `pytest tests/codeintel_rev/ -v`
- [ ] Run integration test: `pytest tests/codeintel_rev/test_integration_full.py -v`
- [ ] Start server and verify `/metrics` endpoint shows expected metrics
- [ ] Verify Grafana dashboards (if available) render correctly

**Phase 2 Success Criteria**:
- ✅ 60+ total lines removed across both adapters
- ✅ All tests pass (unit + integration)
- ✅ Metrics backward compatible (100%)
- ✅ Zero Ruff/pyright/pyrefly errors

---

## Phase 3: Error Handling Standardization

**Duration**: 1 day  
**Risk**: Low  
**Rollback**: Yes (incremental updates)

### 3.1 Enhance Error Handling Module

- [ ] Open `codeintel_rev/mcp_server/error_handling.py`
- [ ] Add `EXCEPTION_TO_ERROR_CODE` mapping dict with:
  - [ ] `PathOutsideRepository` → ("path_outside_repo", 400)
  - [ ] `PathNotDirectory` → ("path_not_directory", 400)
  - [ ] `PathNotFound` → ("path_not_found", 404)
  - [ ] `VectorSearchError` → ("vector_search_failed", 500)
  - [ ] `EmbeddingError` → ("embedding_failed", 500)
  - [ ] `NotImplementedError` → ("not_implemented", 501)
- [ ] Add `format_error_response(exc: Exception) -> dict` function
  - [ ] Maps exception to RFC 9457 Problem Details format
  - [ ] Includes type, title, status, detail, code fields
  - [ ] Fallback for unregistered exceptions (generic 500)

### 3.2 Update Adapters to Use Standardized Errors

**Note**: Adapters currently handle errors via exceptions raised to MCP layer. This phase documents the pattern rather than changing adapter code.

- [ ] Verify adapters raise exceptions (not return error dicts):
  - [ ] `text_search.py` raises `VectorSearchError` on failures
  - [ ] `semantic.py` raises `VectorSearchError` and `EmbeddingError`
  - [ ] `files.py` raises `PathOutsideRepository`, `PathNotFound`
  - [ ] `history.py` raises similar path exceptions
- [ ] Document error mapping in architecture guide (Phase 4)

### 3.3 Add Error Handling Tests

- [ ] Create `tests/codeintel_rev/test_error_handling.py` (or enhance existing)
  - [ ] Test `format_error_response()` for each exception type
  - [ ] Verify Problem Details structure (type, title, status, detail, code)
  - [ ] Test fallback for unknown exception types
  - [ ] Verify HTTP status codes match expectations

### 3.4 Validation (Error Handling)

- [ ] Run `uv run ruff format codeintel_rev/mcp_server/error_handling.py`
- [ ] Run `uv run ruff check --fix codeintel_rev/mcp_server/error_handling.py`
- [ ] Run `uv run pyright codeintel_rev/mcp_server/error_handling.py`
- [ ] Run `uv run pyrefly check codeintel_rev/mcp_server/error_handling.py`
- [ ] Run `SKIP_GPU_WARMUP=1 uv run pytest tests/codeintel_rev/test_error_handling.py -v`

**Success Criteria** (Error Handling):
- ✅ Consistent RFC 9457 format across all error paths
- ✅ All exception types mapped to appropriate HTTP status codes
- ✅ Tests verify error structure and codes
- ✅ No Ruff/pyright/pyrefly errors

---

## Phase 4: Documentation and Validation

**Duration**: 1 day  
**Risk**: Low  
**Rollback**: N/A (documentation only)

### 4.1 Create Architecture Documentation

- [ ] Create `codeintel_rev/docs/architecture/observability.md` with:
  - [ ] **Overview** - Purpose of unified observability helper
  - [ ] **Integration with kgfoundry_common** - How common module wraps kgfoundry_common.observability
  - [ ] **Usage Patterns** - Code examples for adapters
  - [ ] **Metrics Naming Conventions** - operation/component labeling standards
  - [ ] **Resource Cleanup Best Practices** with examples:
    - [ ] HTTP client lifecycle (VLLMClient.close() in lifespan)
    - [ ] DuckDB catalog context managers (open_catalog pattern)
    - [ ] FAISS manager resource management
  - [ ] **Error Handling** - RFC 9457 Problem Details format examples
  - [ ] **Testing Observability** - How to test metrics and error responses
  - [ ] **Junior Developer Guide** - Step-by-step for adding observability to new adapters

### 4.2 Update Existing Documentation

- [ ] Update `codeintel_rev/README.md`:
  - [ ] Add link to architecture/observability.md
  - [ ] Update observability section (if exists)
- [ ] Update `codeintel_rev/docs/CONFIGURATION.md` (if observability config mentioned)

### 4.3 Generate Artifacts

- [ ] Run `make artifacts` from project root
- [ ] Verify no unexpected diffs: `git diff --exit-code docs/_build/`
- [ ] If diffs exist, review and commit (may be doc updates from new code)

### 4.4 OpenSpec Validation

- [ ] Run `openspec validate codeintel-metrics-harmonization --strict`
- [ ] Fix any validation errors (missing scenarios, malformed requirements)
- [ ] Re-run until validation passes

### 4.5 Final Quality Gates

- [ ] Run full quality gate sequence:
  ```bash
  uv run ruff format
  uv run ruff check --fix
  uv run pyright --warnings --pythonversion=3.13
  uv run pyrefly check
  SKIP_GPU_WARMUP=1 uv run pytest tests/codeintel_rev/ -v --cov=codeintel_rev
  make artifacts && git diff --exit-code
  python tools/check_new_suppressions.py codeintel_rev/
  python tools/check_imports.py
  ```
- [ ] Verify zero errors in all tools
- [ ] Verify test coverage ≥ 95% on new code
- [ ] Verify no new suppressions added

### 4.6 Manual Verification Checklist

- [ ] Start codeintel server: `uvicorn codeintel_rev.app.main:app --reload`
- [ ] Perform text search via MCP tool
- [ ] Perform semantic search via MCP tool
- [ ] Check `/metrics` endpoint shows expected metrics
- [ ] Check logs for structured observability fields (operation, component, duration_ms)
- [ ] Verify error responses have Problem Details format
- [ ] Check `/readyz` endpoint returns healthy status

**Phase 4 Success Criteria**:
- ✅ Architecture documentation complete and junior-developer friendly
- ✅ All quality gates pass (zero errors)
- ✅ OpenSpec validation passes
- ✅ Manual verification checklist complete
- ✅ Ready for PR submission

---

## Rollout Checklist

### Pre-Merge Validation

- [ ] All tasks above checked off
- [ ] All quality gates pass
- [ ] OpenSpec validation passes (`openspec validate codeintel-metrics-harmonization --strict`)
- [ ] PR created with:
  - [ ] Link to this proposal
  - [ ] Task completion snapshot
  - [ ] Manual verification evidence (screenshots/logs)
  - [ ] Metrics backward compatibility proof

### Post-Merge Monitoring

- [ ] Monitor Grafana dashboards for metric continuity
- [ ] Check error logs for unexpected Problem Details format issues
- [ ] Verify no performance regressions in semantic search
- [ ] Confirm adapter code duplication eliminated (60+ lines)

### Rollback Plan

If issues arise post-merge:

**Per-Adapter Rollback** (safest):
1. Revert specific adapter commit (text_search or semantic)
2. Run tests to verify rollback successful
3. Deploy reverted version

**Full Rollback** (nuclear option):
1. Revert all commits from Phase 1-3
2. Run full test suite
3. Deploy reverted version

**Rollback Time**: < 15 minutes (simple revert + deploy)

---

## Success Metrics Summary

| Metric | Target | Actual |
|--------|--------|--------|
| Lines of code removed | 60+ | ___ |
| Test coverage on new code | ≥ 95% | ___ |
| Backward compatibility | 100% | ___ |
| Quality gate errors | 0 | ___ |
| Documentation pages | 1 (architecture guide) | ___ |
| Adapters refactored | 2 (text_search, semantic) | ___ |

---

## Notes for Implementers

- **Incremental approach**: Each phase can be merged independently
- **Test-driven**: Write/update tests before refactoring adapters
- **Backward compatibility**: Verify metrics output before/after each phase
- **Documentation-first**: Create architecture guide early for reference during implementation

