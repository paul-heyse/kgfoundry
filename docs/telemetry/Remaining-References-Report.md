# Remaining Observability/Telemetry References Report

## Summary
This report identifies all remaining references to observability, telemetry, metrics, and prometheus code in the `codeintel_rev` package.

## Still Existing Modules (Need to be Deleted or Made No-Op)

### 1. `codeintel_rev/observability/` directory
- `__init__.py` - exports observability modules
- `execution_ledger.py` - execution ledger for diagnostics
- `reporting.py` - run report rendering utilities
- `semantic_conventions.py` - semantic attribute constants
- `timeline.py` - Timeline class for event tracking

### 2. `codeintel_rev/mcp_server/telemetry.py`
- Contains `ToolRunContext` and `tool_operation_scope()` 
- Used for tracking MCP tool invocations
- Currently just logs events (no metrics)

### 3. `codeintel_rev/retrieval/telemetry.py`
- Contains `StageTiming`, `track_stage()`, `record_stage_decision()`
- Used for tracking retrieval pipeline stage timing
- Currently just logs events (no metrics)

## Files Importing Observability/Telemetry Code

### High Priority (Core Functionality)

1. **`codeintel_rev/mcp_server/server.py`**
   - Imports: `tool_operation_scope` from `mcp_server.telemetry`
   - Usage: Wraps tool handlers with `with tool_operation_scope(...)`
   - Action: Remove `tool_operation_scope` wrapper, keep tool logic

2. **`codeintel_rev/mcp_server/server_semantic.py`**
   - Imports: `tool_operation_scope` from `mcp_server.telemetry`
   - Usage: Wraps semantic search tools
   - Action: Remove `tool_operation_scope` wrapper

3. **`codeintel_rev/mcp_server/server_symbols.py`**
   - Imports: `tool_operation_scope` from `mcp_server.telemetry`
   - Usage: Wraps symbol search tools
   - Action: Remove `tool_operation_scope` wrapper

4. **`codeintel_rev/mcp_server/adapters/semantic_pro.py`**
   - Imports: `StageTiming`, `track_stage`, `record_stage_decision` from `retrieval.telemetry`
   - Usage: Tracks stage timing in retrieval pipeline
   - Action: Remove `track_stage()` context managers and `record_stage_decision()` calls

### Medium Priority (Diagnostics/Reporting)

5. **`codeintel_rev/app/routers/diagnostics.py`**
   - Imports: `execution_ledger` from `observability`
   - Usage: Provides `/diagnostics/run_report/{run_id}` endpoints
   - Action: Remove diagnostics endpoints or make them no-op

6. **`codeintel_rev/diagnostics/report_cli.py`**
   - Imports: `LedgerRunReport`, `infer_stop_reason`, `load_ledger` from `observability.run_report`
   - Usage: CLI command for rendering run reports
   - Action: Remove CLI command or make it no-op

### Low Priority (Runtime Infrastructure)

7. **`codeintel_rev/runtime/cells.py`**
   - Imports: `Timeline`, `current_timeline` from `observability.timeline`
   - Usage: Captures timeline in `RuntimeCellInitContext`
   - Action: Remove timeline from context, keep other fields

8. **`codeintel_rev/observability/reporting.py`**
   - Imports: `Timeline` from `observability.timeline`
   - Usage: Renders timeline reports
   - Action: Delete entire module

## Files with Comments/Docstrings Only

These files mention observability/telemetry in comments/docstrings but don't import:
- Various files in `codeintel_rev/` with docstring references
- Should be cleaned up but lower priority

## Recommended Action Plan

1. **Remove `tool_operation_scope` wrappers** from server files (3 files)
2. **Remove `track_stage()` and `record_stage_decision()`** from `semantic_pro.py`
3. **Remove diagnostics endpoints** or make them no-op
4. **Remove timeline from RuntimeCell** context
5. **Delete entire `observability/` directory**
6. **Delete `mcp_server/telemetry.py`** (or make it no-op if needed for API compatibility)
7. **Delete `retrieval/telemetry.py`** (or make it no-op if needed for API compatibility)
8. **Clean up docstrings/comments** mentioning observability

## Notes

- `tool_operation_scope` currently only does logging, not metrics
- `track_stage` and `record_stage_decision` currently only do logging
- These could be replaced with direct logging calls if needed
- Timeline is used for diagnostics/reporting which is observability-related

