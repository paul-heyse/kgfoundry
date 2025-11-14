# Telemetry Scope: Proposed Structural Fixes

## Error Analysis Summary

### Pyright Errors (17 total)
1. **Frozen dataclass mutations** (9 errors):
   - `flight_recorder.py`: `_RunBuffer` fields being mutated directly
   - `ledger.py`: `RunLedger._handle` being mutated directly
   - `otel_metrics.py`: `_GaugeEntry.value` being mutated directly

2. **Type safety issues** (5 errors):
   - `metrics.py`: Optional module access without guards
   - `otel.py`: Resource type mismatch (`object` vs `Resource`)
   - Test files: `InMemorySpanExporter` import errors

3. **Import issues** (3 errors):
   - Test files importing optional OpenTelemetry SDK components

### Pyrefly Errors (15 total)
- Same frozen dataclass issues as Pyright
- Type narrowing issues with optional modules

### Ruff Errors (17 total)
1. **Code quality**:
   - Unsorted `__all__` exports
   - Import block ordering
   - Complexity violations (`render_markdown_v2`, `init_telemetry`)
   - Global statement usage
   - Blind exception catching

2. **Style issues**:
   - Commented-out code
   - Module-level imports not at top

---

## Proposed Fixes (Aligned with AGENTS.md)

### Fix Category 1: Frozen Dataclass Mutations → Immutable Updates

**Principle**: Use `dataclasses.replace()` for immutable updates, preserving immutability guarantees.

#### 1.1 `flight_recorder.py` - `_RunBuffer` mutations

**Current Issue**: Direct field assignment on frozen dataclass
```python
buffer.started_ns = buffer.started_ns or start_ns  # ❌ Fails
buffer.session_id = buffer.session_id or session  # ❌ Fails
```

**Proposed Fix**: Use `replace()` pattern with helper functions
```python
from dataclasses import replace

# Helper functions return new instances
def _update_identities(buffer: _RunBuffer, span: object) -> _RunBuffer:
    """Return updated buffer with identity attributes."""
    updates: dict[str, object] = {}
    if isinstance(session, str) and buffer.session_id is None:
        updates["session_id"] = session
    if isinstance(run_id, str) and buffer.run_id is None:
        updates["run_id"] = run_id
    return replace(buffer, **updates) if updates else buffer

# Usage
buffer = _update_identities(buffer, span)
self._buffers[trace_id] = buffer
```

**Benefits**:
- Preserves immutability guarantees
- Clear intent (functional update pattern)
- Type-safe (return type annotation)

#### 1.2 `ledger.py` - `RunLedger._handle` mutations

**Current Issue**: `_handle` is frozen but needs lazy initialization

**Proposed Fix**: Make `_handle` mutable OR use a different pattern
```python
# Option A: Make handle mutable (preferred for I/O handles)
@dataclass(slots=True, frozen=False)  # Only _handle is mutable
class RunLedger:
    run_id: str
    session_id: str | None
    path: Path
    _handle: io.TextIOWrapper | None = field(default=None, init=False)

# Option B: Use a separate mutable wrapper (more complex)
```

**Recommendation**: Option A - I/O handles are inherently mutable state, so making this field mutable is appropriate.

#### 1.3 `otel_metrics.py` - `_GaugeEntry.value` mutations

**Current Issue**: Frozen dataclass entry being mutated

**Proposed Fix**: Replace entire entry in dictionary
```python
def set_value(self, key: tuple[tuple[str, object], ...], value: float) -> None:
    """Store value for the attribute tuple."""
    with self._lock:
        entry = self._entries.get(key)
        if entry is None:
            entry = _GaugeEntry(attributes=dict(key), value=float(value))
        else:
            entry = replace(entry, value=float(value))  # ✅ Immutable update
        self._entries[key] = entry
```

---

### Fix Category 2: Type Safety & Narrowing

**Principle**: Use type guards and proper narrowing to eliminate `Any` and optional access issues.

#### 2.1 `metrics.py` - Optional module access

**Current Issue**: Accessing attributes on potentially `None` modules
```python
metrics_sdk = _import_module("opentelemetry.sdk.metrics")
# ...
provider = metrics_sdk.MeterProvider(...)  # ❌ metrics_sdk could be None
```

**Proposed Fix**: Type guards and early returns
```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType

def _import_module(name: str) -> ModuleType | None:
    """Import module with proper return type."""
    try:
        return importlib.import_module(name)
    except ImportError:
        return None

def install_metrics_provider(resource: Resource, *, otlp_endpoint: str | None = None) -> None:
    """Install a global MeterProvider with OTLP + Prometheus readers."""
    global _METRICS_PROVIDER_INSTALLED
    if _METRICS_PROVIDER_INSTALLED:
        return
    
    metrics_sdk = _import_module("opentelemetry.sdk.metrics")
    view_module = _import_module("opentelemetry.sdk.metrics.view")
    export_module = _import_module("opentelemetry.sdk.metrics.export")
    metrics_api = _import_module("opentelemetry.metrics")
    
    # Type guard: early return if any required module is missing
    if None in (metrics_sdk, view_module, export_module, metrics_api):
        LOGGER.debug("OpenTelemetry metrics components unavailable; skipping meter install")
        return
    
    # Now type checkers know these are not None
    assert metrics_sdk is not None  # Type narrowing
    assert view_module is not None
    assert export_module is not None
    assert metrics_api is not None
    
    # Safe access
    provider = metrics_sdk.MeterProvider(...)
    metrics_api.set_meter_provider(provider)
```

**Alternative (cleaner)**: Use a helper that returns typed modules
```python
@dataclass(frozen=True)
class _MetricsModules:
    """Type-safe container for metrics SDK modules."""
    sdk: ModuleType
    view: ModuleType
    export: ModuleType
    api: ModuleType

def _load_metrics_modules() -> _MetricsModules | None:
    """Load all required metrics modules or return None."""
    sdk = _import_module("opentelemetry.sdk.metrics")
    view = _import_module("opentelemetry.sdk.metrics.view")
    export = _import_module("opentelemetry.sdk.metrics.export")
    api = _import_module("opentelemetry.metrics")
    if None in (sdk, view, export, api):
        return None
    return _MetricsModules(
        sdk=sdk, view=view, export=export, api=api
    )
```

#### 2.2 `otel.py` - Resource type mismatch

**Current Issue**: `resource` is typed as `object` but needs `Resource`

**Proposed Fix**: Proper type annotation in `_build_resource`
```python
def _build_resource(
    handles: _TraceHandles,
    service_name: str,
    service_version: str | None,
) -> object:  # ❌ Too generic
```

**Proposed Fix**:
```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opentelemetry.sdk.resources import Resource

def _build_resource(
    handles: _TraceHandles,
    service_name: str,
    service_version: str | None,
) -> Resource:  # ✅ Specific type
    # Implementation returns Resource instance
    resource = handles.resource.Resource.create(resource_attrs)
    return _merge_detected_resources(resource)
```

#### 2.3 Test files - Optional imports

**Current Issue**: `InMemorySpanExporter` import fails when OTel SDK not installed

**Proposed Fix**: Already implemented with try/except, but improve type hints
```python
try:
    from opentelemetry.sdk.trace.export import (
        InMemorySpanExporter,
        SimpleSpanProcessor,
    )
    OTELEMETRY_AVAILABLE = True
except ImportError:
    # Create stub types for type checking
    if TYPE_CHECKING:
        from typing import Any
        InMemorySpanExporter = Any  # type: ignore[assignment,misc]
        SimpleSpanProcessor = Any  # type: ignore[assignment,misc]
    OTELEMETRY_AVAILABLE = False
```

---

### Fix Category 3: Code Quality Improvements

**Principle**: Reduce complexity, eliminate globals, improve maintainability.

#### 3.1 Complexity reduction

**Issue**: `init_telemetry` has 13 branches (>12 limit)

**Proposed Fix**: Extract helper functions
```python
def _should_enable_telemetry() -> bool:
    """Determine if telemetry should be enabled."""
    # Consolidate env flag checks

def _initialize_tracing(...) -> tuple[ModuleType | None, object | None]:
    """Initialize tracing provider."""
    # Extract tracing logic

def _initialize_metrics(...) -> None:
    """Initialize metrics provider."""
    # Extract metrics logic

def init_telemetry(...) -> None:
    """Best-effort OpenTelemetry bootstrap."""
    if not _should_enable_telemetry():
        return
    trace_module, provider = _initialize_tracing(...)
    if trace_module:
        _initialize_metrics(...)
```

**Issue**: `render_markdown_v2` complexity (11 > 10)

**Proposed Fix**: Extract formatting helpers
```python
def _format_stage_table(stages: list[RunReportStage]) -> list[str]:
    """Format stages as markdown table rows."""
    # Extract table formatting

def _format_budgets(budgets: Mapping[str, Any] | None) -> list[str]:
    """Format budgets section."""
    # Extract budget formatting

def render_markdown_v2(report: RunReportV2) -> str:
    """Render RunReportV2 as Markdown."""
    lines = _build_header(report)
    lines.extend(_format_budgets(report.budgets))
    lines.extend(_format_stage_table(report.stages))
    # ...
```

#### 3.2 Global statement elimination

**Issue**: `_METRICS_PROVIDER_INSTALLED` and `_PROM_HTTP_SERVER_STARTED` use globals

**Proposed Fix**: Use a state class (thread-safe singleton pattern)
```python
@dataclass(frozen=False, slots=True)
class _MetricsState:
    """Thread-safe metrics provider state."""
    provider_installed: bool = False
    prom_server_started: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

_METRICS_STATE = _MetricsState()

def install_metrics_provider(...) -> None:
    """Install metrics provider (idempotent)."""
    with _METRICS_STATE._lock:
        if _METRICS_STATE.provider_installed:
            return
        # ... install logic ...
        _METRICS_STATE.provider_installed = True
```

**Benefits**:
- Thread-safe
- No global statements
- Easier to test (can inject state)
- Clear state management

#### 3.3 Exception handling

**Issue**: Blind `except Exception` in `telemetry/logging.py`

**Proposed Fix**: Narrow exception types
```python
try:
    # ... logging setup ...
except (RuntimeError, ValueError, OSError, ImportError) as exc:
    LOGGER.debug("Failed to initialize structured logging", exc_info=exc)
```

#### 3.4 Import organization

**Issues**: 
- Unsorted `__all__`
- Import blocks not sorted
- Module-level imports not at top

**Proposed Fix**: Use ruff auto-fix + manual review
```bash
uv run ruff check --fix codeintel_rev/observability codeintel_rev/telemetry codeintel_rev/metrics
```

#### 3.5 Commented code removal

**Issue**: Commented code in `semantic_conventions.py`

**Proposed Fix**: Remove commented code (already addressed in previous edit)

---

## Implementation Plan

### Phase 1: Critical Type Safety (High Priority)
1. ✅ Fix frozen dataclass mutations in `flight_recorder.py` (already started)
2. Fix `ledger.py` `_handle` mutation
3. Fix `otel_metrics.py` `_GaugeEntry` mutation
4. Fix `metrics.py` optional module access
5. Fix `otel.py` Resource type annotation

### Phase 2: Test Infrastructure (High Priority)
6. Fix test import issues with proper TYPE_CHECKING guards

### Phase 3: Code Quality (Medium Priority)
7. Reduce complexity in `init_telemetry` and `render_markdown_v2`
8. Replace global statements with state class
9. Narrow exception handling
10. Fix import organization (auto-fix)

### Phase 4: Validation (Required)
11. Run full test suite
12. Verify pyright/pyrefly/ruff all pass
13. Check for regressions

---

## Design Decisions

### Why `dataclasses.replace()` over mutable fields?

**Rationale**: 
- Preserves immutability guarantees (important for thread safety)
- Makes state transitions explicit
- Easier to reason about (functional style)
- Aligns with AGENTS.md principle #7 (modularity & structure)

**Exception**: I/O handles (`RunLedger._handle`) remain mutable because:
- File handles are inherently mutable state
- Lazy initialization pattern requires mutation
- Thread safety handled by external locking

### Why state class over globals?

**Rationale**:
- Eliminates global statement warnings
- Thread-safe by design (lock included)
- Easier to test (can inject mock state)
- Clear ownership of state

### Why extract complexity?

**Rationale**:
- AGENTS.md complexity limits (≤10 branches)
- Improves testability (smaller units)
- Better error isolation
- Easier to maintain

---

## Questions for Review

1. **Frozen dataclass pattern**: Do you prefer `replace()` everywhere, or is making `_handle` mutable acceptable?

2. **State management**: State class vs. module-level variables with locks - preference?

3. **Type narrowing**: Assert statements vs. type guards - which pattern do you prefer?

4. **Complexity extraction**: Should we extract helpers even if it increases file count?

5. **Test imports**: Should we create stub types for missing imports, or keep current try/except pattern?

---

## Expected Outcomes

After fixes:
- ✅ Zero pyright errors
- ✅ Zero pyrefly errors  
- ✅ Zero ruff errors (except possibly complexity if we decide to keep as-is)
- ✅ All tests pass
- ✅ Type safety improved (no `Any` in public APIs)
- ✅ Code quality improved (complexity reduced, globals eliminated)

