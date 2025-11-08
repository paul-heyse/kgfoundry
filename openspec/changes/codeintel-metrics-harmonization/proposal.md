## Why

The CodeIntel MCP implementation currently duplicates observability and metrics boilerplate across multiple adapters, violating AGENTS.md design principles (Section 6 of the design review). This creates three critical maintenance and quality issues:

1. **Duplicated Metrics Boilerplate**: Each adapter (`text_search.py`, `semantic.py`) implements its own identical `_NoopObservation` class and `_observe` context manager (30+ lines of duplicated code)
2. **Inconsistent Error Handling**: Adapters return errors in different formats (Problem Details in text_search vs. custom shapes in files/history), making client error handling complex
3. **Missed Integration Opportunity**: Existing `kgfoundry_common.observability` infrastructure (MetricsProvider, observe_duration) not leveraged in codeintel adapters

This violates "Section 6: Holistic Future-Proofing and Best Practices" from the design review which emphasizes:
- "focus on modularizing common code and clearly delineating what is implemented"
- "no adapter should directly access global state or other adapters; all cross-component interaction goes through ServiceContext or well-defined interfaces"
- Resource cleanup best practices for HTTP clients

## What Changes

- **ADDED**: `codeintel_rev/mcp_server/common/observability.py` — unified observability helper
  - Single `observe_duration()` context manager with noop fallback
  - Integrates with `kgfoundry_common.observability.MetricsProvider`
  - Eliminates 30+ lines of duplicated code per adapter

- **MODIFIED**: `codeintel_rev/mcp_server/adapters/text_search.py` — remove local boilerplate
  - Remove `_NoopObservation` class (15 lines)
  - Remove `_observe()` helper (10 lines)
  - Import and use `observe_duration` from common module
  - Maintain identical metrics behavior (backward compatible)

- **MODIFIED**: `codeintel_rev/mcp_server/adapters/semantic.py` — remove local boilerplate
  - Remove `_NoopObservation` class (15 lines)
  - Remove `_observe()` helper (10 lines)
  - Import and use `observe_duration` from common module
  - Maintain identical metrics behavior (backward compatible)

- **MODIFIED**: `codeintel_rev/mcp_server/error_handling.py` — standardize error responses
  - Add consistent error mapper for all exceptions
  - Map to RFC 9457 Problem Details format
  - Centralize error code → HTTP status mapping

- **ADDED**: `codeintel_rev/docs/architecture/observability.md` — observability patterns documentation
  - Documents unified observability helper usage
  - Describes integration with kgfoundry_common infrastructure
  - Provides resource cleanup best practices (HTTP clients, DuckDB connections)
  - Junior developer friendly with examples

- **ADDED**: Comprehensive test suite
  - `tests/codeintel_rev/test_observability_common.py` — unit tests for shared helper
  - Update existing adapter tests to verify new helper usage
  - Coverage: 95%+ on new observability code

## Impact

- **Specs**: New capability `codeintel-observability` describing unified observability patterns
- **Affected code**: 
  - Core: `codeintel_rev/mcp_server/common/` (new observability.py)
  - Adapters: `codeintel_rev/mcp_server/adapters/text_search.py`, `semantic.py` (boilerplate removed)
  - Error handling: `codeintel_rev/mcp_server/error_handling.py` (standardized)
  - Docs: New architecture documentation for observability patterns
- **Data contracts**: No schema changes; internal refactoring only
- **Breaking changes**: None for external API; internal adapter code simplified (non-breaking for callers)
- **Rollout**: 
  - Phase 1: Create common observability module (backward compatible, no existing code touched)
  - Phase 2: Refactor text_search adapter (incremental, testable)
  - Phase 3: Refactor semantic adapter (incremental, testable)
  - Phase 4: Documentation and validation (no code changes)
- **Metrics compatibility**: 100% backward compatible; same metric names, labels, and behavior
- **Resource cleanup**: VLLMClient cleanup already implemented (line 202 in main.py); documented in new architecture guide

## Dependencies

- Leverages existing `kgfoundry_common.observability.MetricsProvider` infrastructure
- Builds on existing error taxonomy (`kgfoundry_common.errors`)
- Maintains compatibility with current Prometheus metrics infrastructure
- No new external dependencies required

## Alignment with AGENTS.MD

This change directly implements guidance from Section 6 ("Holistic Future-Proofing and Best Practices") of the design review:

✅ **Modularized common code** - Metrics helpers centralized in common module  
✅ **Documented architecture choices** - New observability.md explains patterns and rationale  
✅ **Resource cleanup** - HTTP client lifecycle documented with examples  
✅ **Extensibility** - Well-defined interfaces for cross-component interaction  
✅ **Developer guide quality** - Junior developer friendly documentation  
✅ **Best-in-class Python practices** - DRY, explicit dependencies, type-safe  

