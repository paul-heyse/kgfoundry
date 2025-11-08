## Context

### Current State: Duplicated Observability Boilerplate

The CodeIntel MCP server currently implements identical metrics and observability boilerplate in multiple adapters. This violates the DRY principle and AGENTS.MD design standards outlined in Section 6 of the design review.

#### Duplicated Code Pattern

Both `text_search.py` and `semantic.py` contain **identical 30-line boilerplate**:

```python
# codeintel_rev/mcp_server/adapters/text_search.py (lines 39-85)
def _supports_histogram_labels(histogram: object) -> bool:
    labelnames = getattr(histogram, "_labelnames", None)
    if labelnames is None:
        return True
    try:
        return len(tuple(labelnames)) > 0
    except TypeError:
        return False

_METRICS_ENABLED = _supports_histogram_labels(METRICS.operation_duration_seconds)

class _NoopObservation:
    """Fallback observation when Prometheus metrics are unavailable."""
    def mark_error(self) -> None:
        """No-op error marker."""
    def mark_success(self) -> None:
        """No-op success marker."""

@contextmanager
def _observe(operation: str) -> Iterator[DurationObservation | _NoopObservation]:
    """Yield a metrics observation, falling back to a no-op when metrics are disabled."""
    if not _METRICS_ENABLED:
        yield _NoopObservation()
        return
    try:
        with observe_duration(METRICS, operation, component=COMPONENT_NAME) as observation:
            yield observation
            return
    except ValueError:
        yield _NoopObservation()
```

**This exact pattern is duplicated in `semantic.py` (lines 37-83).**

#### Problems with Current Approach

1. **30+ lines of duplicated code** across 2 adapters (60 lines total)
2. **Maintenance burden**: bug fixes must be applied twice
3. **Inconsistency risk**: implementations can diverge over time
4. **Missed abstraction opportunity**: kgfoundry_common.observability already provides this functionality
5. **Testing overhead**: identical logic tested redundantly

### Existing Infrastructure Not Leveraged

The repository already has production-grade observability infrastructure:

```python
# src/kgfoundry_common/observability.py (lines 1-198)
class MetricsProvider:
    """Provide component-level metrics for long-running operations."""
    runs_total: CounterLike
    operation_duration_seconds: HistogramLike
    # ...

@contextmanager
def observe_duration(
    provider: MetricsProvider,
    operation: str,
    *,
    component: str,
) -> Iterator[DurationObservation]:
    """Context manager for timing operations with automatic metrics recording."""
    # ...
```

**Codeintel adapters reimplement this rather than using it directly.**

### Resource Cleanup Status

The design review emphasizes resource cleanup (Section 6: "Resource Cleanup"). Current state:

✅ **Already Implemented**: VLLMClient HTTP connection cleanup in lifespan (line 202 in main.py)
✅ **Already Implemented**: DuckDB catalog uses context managers (open_catalog pattern)
❌ **Not Documented**: Best practices scattered across code, no central guide

## Goals

### Primary Goals

1. **Eliminate Code Duplication**
   - Remove all duplicated observability boilerplate from adapters
   - Centralize metrics helpers in single common module
   - Reduce total lines of code by 60+ lines

2. **Integrate with Existing Infrastructure**
   - Leverage `kgfoundry_common.observability.MetricsProvider` directly
   - Use existing `observe_duration` helper where possible
   - Maintain consistency with rest of codebase

3. **Standardize Error Handling**
   - Unified error envelope schema across all adapters
   - Consistent RFC 9457 Problem Details format
   - Single error mapping function for all exceptions

4. **Document Best Practices**
   - Centralized observability patterns guide
   - Resource cleanup lifecycle documentation
   - Junior developer friendly with examples

5. **Maintain 100% Backward Compatibility**
   - Same metric names, labels, and behavior
   - No changes to external API surface
   - Internal refactoring only

### Non-Goals

- **NOT changing metrics names/labels** (backward compatible)
- **NOT adding new observability features** (pure consolidation)
- **NOT modifying adapter public APIs** (internal refactoring)
- **NOT implementing distributed tracing** (deferred to separate proposal)

## Decisions

### Decision 1: Single Common Observability Module

**What**: Create `codeintel_rev/mcp_server/common/observability.py` as single source of truth for metrics helpers.

**Why**: 
- Eliminates 60+ lines of duplicated code
- Single place to fix bugs and add features
- Easier to maintain consistency with kgfoundry_common
- Clear module structure following AGENTS.MD patterns

**Alternative Considered**: Import directly from `kgfoundry_common.observability`
- **Rejected**: Codeintel needs custom component name handling and noop fallback logic specific to adapter patterns

**Implementation**:

```python
# codeintel_rev/mcp_server/common/observability.py
from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Iterator

from kgfoundry_common.observability import MetricsProvider, DurationObservation

if TYPE_CHECKING:
    pass

def _supports_histogram_labels(histogram: object) -> bool:
    """Check if histogram supports labeled metrics."""
    labelnames = getattr(histogram, "_labelnames", None)
    if labelnames is None:
        return True
    try:
        return len(tuple(labelnames)) > 0
    except TypeError:
        return False

class _NoopObservation:
    """Fallback observation when Prometheus metrics are unavailable."""
    def mark_error(self) -> None:
        """No-op error marker."""
    def mark_success(self) -> None:
        """No-op success marker."""

@contextmanager
def observe_duration(
    operation: str,
    component: str,
    *,
    metrics: MetricsProvider | None = None,
) -> Iterator[DurationObservation | _NoopObservation]:
    """Yield a metrics observation with graceful degradation.
    
    Parameters
    ----------
    operation : str
        Operation name for metrics labeling.
    component : str
        Component name for metrics labeling.
    metrics : MetricsProvider | None, optional
        Metrics provider instance. If None, uses MetricsProvider.default().
    
    Yields
    ------
    DurationObservation | _NoopObservation
        Metrics observation when Prometheus is configured, otherwise a no-op recorder.
    
    Examples
    --------
    >>> from codeintel_rev.mcp_server.common.observability import observe_duration
    >>> with observe_duration("search", "text_search") as obs:
    ...     # perform operation
    ...     obs.mark_success()
    """
    provider = metrics or MetricsProvider.default()
    if not _supports_histogram_labels(provider.operation_duration_seconds):
        yield _NoopObservation()
        return
    try:
        with kgfoundry_common.observability.observe_duration(
            provider, operation, component=component
        ) as observation:
            yield observation
            return
    except ValueError:
        yield _NoopObservation()

__all__ = ["observe_duration"]
```

### Decision 2: Incremental Adapter Refactoring

**What**: Refactor adapters one-at-a-time in separate commits.

**Why**:
- Smaller changesets easier to review
- Can roll back individual adapters if issues found
- Tests isolate regressions to specific adapter
- Parallel development possible (different developers per adapter)

**Rollout Order**:
1. `text_search.py` (simpler, good test case)
2. `semantic.py` (more complex, benefits from text_search learnings)

### Decision 3: Standardized Error Responses

**What**: All adapters use consistent RFC 9457 Problem Details format via centralized error mapper.

**Why**:
- Client error handling simplified (single schema)
- Easier debugging with structured error codes
- Consistency with rest of kgfoundry codebase
- Follows AGENTS.MD RFC 9457 requirements

**Implementation**:

```python
# codeintel_rev/mcp_server/error_handling.py (ENHANCED)
from kgfoundry_common.errors import KgFoundryError

EXCEPTION_TO_ERROR_CODE = {
    PathOutsideRepository: ("path_outside_repo", 400),
    PathNotDirectory: ("path_not_directory", 400),
    PathNotFound: ("path_not_found", 404),
    NotImplementedError: ("not_implemented", 501),
    VectorSearchError: ("vector_search_failed", 500),
    EmbeddingError: ("embedding_failed", 500),
}

def format_error_response(exc: Exception) -> dict:
    """Convert exception to RFC 9457 Problem Details format.
    
    Parameters
    ----------
    exc : Exception
        Exception to format.
    
    Returns
    -------
    dict
        Problem Details payload with error code, message, and status.
    """
    for exc_type, (code, status) in EXCEPTION_TO_ERROR_CODE.items():
        if isinstance(exc, exc_type):
            return {
                "problem": {
                    "type": f"https://kgfoundry.dev/problems/{code}",
                    "title": exc_type.__name__,
                    "status": status,
                    "detail": str(exc),
                    "code": code,
                },
                "status": status,
            }
    # Fallback for unregistered exceptions
    return {
        "problem": {
            "type": "https://kgfoundry.dev/problems/internal_error",
            "title": "InternalError",
            "status": 500,
            "detail": str(exc),
            "code": "internal_error",
        },
        "status": 500,
    }
```

### Decision 4: Architecture Documentation

**What**: Create `codeintel_rev/docs/architecture/observability.md` documenting patterns and best practices.

**Why**:
- Single source of truth for observability patterns
- Junior developer onboarding guide
- Documents resource cleanup lifecycle
- Explains integration with kgfoundry_common

**Contents**:
- Unified observability helper usage
- Resource cleanup best practices (HTTP clients, DuckDB)
- Metrics naming conventions
- Error handling patterns
- Code examples

## Relationship to Existing Infrastructure

### Integration with kgfoundry_common.observability

The new common module **wraps** (not replaces) `kgfoundry_common.observability`:

```
codeintel adapters
       ↓ (import)
codeintel_rev/mcp_server/common/observability.py
       ↓ (wraps)
kgfoundry_common/observability.py (MetricsProvider, observe_duration)
       ↓ (uses)
kgfoundry_common/prometheus.py (build_counter, build_histogram)
       ↓ (optional dependency)
prometheus_client (or noop stubs)
```

**Key differences from direct import**:
- Component name defaulting to "codeintel_mcp"
- Custom noop fallback logic for histogram label checking
- Simplified API for adapter use cases

### Resource Cleanup Lifecycle

Current implementation (already correct, needs documentation):

```python
# codeintel_rev/app/main.py (lines 190-206)
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        context = ApplicationContext.create()
        app.state.context = context
        # ... startup ...
        yield
    finally:
        # Shutdown: close VLLMClient HTTP connections
        context.vllm_client.close()  # ← CORRECT: cleanup in lifespan
        await readiness.shutdown()
```

**This pattern will be documented in new architecture guide.**

## Risks / Trade-offs

### Risk 1: Breaking Metrics Continuity

**Risk**: Refactoring might change metric label values or timing, breaking Grafana dashboards.

**Mitigation**:
- Maintain exact same metric names and labels
- Add tests verifying metric emission
- Manual validation of metric output before/after

**Rollback**: Revert commits per adapter (incremental rollback)

### Risk 2: Performance Regression

**Risk**: Adding indirection through common module might slow down hot paths.

**Mitigation**:
- Context manager overhead is negligible (< 1μs)
- No additional allocations in happy path
- Benchmark tests in Phase 4 (if needed)

**Rollback**: Performance regression would be caught in tests before merge

### Trade-off: Custom vs Direct Import

**Trade-off**: Custom wrapper adds one module vs importing directly from kgfoundry_common.

**Decision**: Custom wrapper chosen for:
- ✅ Adapter-specific noop logic
- ✅ Component name defaulting
- ✅ Simpler import paths for adapters
- ❌ One additional module to maintain

**Assessment**: Benefits outweigh costs; single small module vs duplicated logic in 4+ adapters.

## Migration

### Phase 1: Create Common Module (No Breaking Changes)

1. Add `codeintel_rev/mcp_server/common/__init__.py`
2. Add `codeintel_rev/mcp_server/common/observability.py` with shared helper
3. Add unit tests in `tests/codeintel_rev/test_observability_common.py`

**Validation**: Tests pass, no existing code touched yet.

### Phase 2: Refactor text_search (Incremental)

1. Import `observe_duration` from common module
2. Remove local `_NoopObservation` and `_observe`
3. Update tests to verify new helper usage
4. Run full test suite

**Rollback**: Revert single commit, text_search returns to original state.

### Phase 3: Refactor semantic (Incremental)

1. Import `observe_duration` from common module
2. Remove local `_NoopObservation` and `_observe`
3. Update tests to verify new helper usage
4. Run full test suite

**Rollback**: Revert single commit, semantic returns to original state.

### Phase 4: Documentation and Cleanup

1. Add `codeintel_rev/docs/architecture/observability.md`
2. Update README with observability patterns
3. Run `make artifacts`

**No Rollback Needed**: Documentation only, no code changes.

## Testing Strategy

### Unit Tests

**New tests**: `tests/codeintel_rev/test_observability_common.py`
- Test `observe_duration` with real MetricsProvider
- Test `observe_duration` with disabled metrics (noop path)
- Test exception handling in observe_duration
- Test mark_success() and mark_error() behavior

**Coverage target**: 95%+ on new observability.py module

### Integration Tests

**Update existing tests**: 
- `tests/codeintel_rev/test_text_search_adapter.py` - verify metrics still emitted
- `tests/codeintel_rev/test_semantic_adapter.py` - verify metrics still emitted

### Validation Tests

**Manual validation checklist**:
- [ ] Prometheus metrics endpoint shows same metrics as before
- [ ] Grafana dashboards render correctly (no missing metrics)
- [ ] Error responses have consistent Problem Details format
- [ ] Log structured fields include observability context

## Success Metrics

- ✅ **Lines of code reduced**: 60+ lines removed (30 per adapter)
- ✅ **Duplication eliminated**: Zero `_NoopObservation` classes in adapters
- ✅ **Test coverage**: 95%+ on new common module
- ✅ **Backward compatibility**: 100% (same metrics, same API)
- ✅ **Documentation quality**: Junior developer can onboard from architecture guide
- ✅ **Quality gates**: Zero Ruff/pyright/pyrefly errors

