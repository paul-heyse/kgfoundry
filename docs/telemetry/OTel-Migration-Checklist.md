# OpenTelemetry Migration Checklist

## Repository Inventory

### Legacy Telemetry Imports

**Status**: No legacy `telemetry.prom` or `telemetry.otel` modules found. The codebase already uses `telemetry.otel_metrics` which is a compatibility layer over OpenTelemetry.

**Current Telemetry Architecture**:
- `observability/otel.py` - Main OTel bootstrap (traces, metrics, logs)
- `observability/metrics.py` - Metrics provider setup with Prometheus reader
- `telemetry/otel_metrics.py` - Compatibility layer (CounterLike, HistogramLike, GaugeLike)
- `metrics/registry.py` - Centralized metric definitions

**Files Using Telemetry**:
- `app/main.py` - Calls `init_all_telemetry()` at startup
- `mcp_server/adapters/*.py` - Use `telemetry.decorators.span_context`
- `retrieval/*.py` - Use `telemetry.steps` and `telemetry.decorators`
- `io/vllm_client.py` - Uses `telemetry.decorators.span_context`
- `io/faiss_manager.py` - Uses `telemetry.decorators.span_context`
- `io/duckdb_catalog.py` - Uses `telemetry.decorators.span_context`
- `io/git_client.py` - Uses `telemetry.decorators.span_context`

### Hot-Path Seams for Span Insertion

**MCP Adapters** (SERVER spans):
- `mcp_server/adapters/semantic.py` - Semantic search tool
- `mcp_server/adapters/semantic_pro.py` - Pro semantic search tool
- `mcp_server/adapters/text_search.py` - Text search tool
- `mcp_server/adapters/history.py` - History tool

**Retrieval Pipeline** (INTERNAL spans):
- `retrieval/hybrid.py` - Hybrid search engine (`gather_channels`, `pool`, `fuse`, `recency_boost`, `hydrate`)
- `retrieval/mcp_search.py` - MCP search adapter
- `retrieval/gating.py` - Gating/budget decisions
- `retrieval/fusion/weighted_rrf.py` - RRF fusion

**IO Clients** (CLIENT spans):
- `io/vllm_client.py` - Embeddings HTTP/in-proc (`embed_batch`)
- `io/faiss_manager.py` - FAISS search (`search`, `search_with_refine`)
- `io/duckdb_catalog.py` - DuckDB queries (`execute`)
- `io/git_client.py` - Git operations (`blame`, `history`)

**Envelope/Telemetry Helpers**:
- `telemetry/decorators.py` - Span decorators
- `telemetry/events.py` - Event emission
- `telemetry/reporter.py` - Run report generation

## Migration Tasks

### ✅ Task 0: Repository Scan & Inventory
- [x] Inventory of telemetry imports
- [x] Inventory of hot-path seams
- [x] Document current architecture

### ✅ Task 1: Single Programmatic OTel Bootstrap
- [x] Verify `observability/otel.py` handles all bootstrap (already implemented)
- [x] Ensure FastAPI instrumentation is wired (via `init_all_telemetry` in `app/main.py`)
- [x] Middleware for session/run ID attributes (already in `app/main.py`)

### ✅ Task 2: Semantic Conventions
- [x] Extend `observability/semantic_conventions.py` with required attributes
- [x] Codebase already uses Attrs constants consistently

### ⚠️ Task 3: Domain Spans & Events
- [x] MCP adapters: Already use `as_span` and `span_context` decorators
- [x] Embeddings: Already use `span_context` and `record_span_event`
- [x] Retrieval: Already use `telemetry.steps` and decorators
- [x] DuckDB: Already uses `span_context` decorator
- [x] Git: Already uses `span_context` decorator
- **Note**: Spans are already implemented across hot paths using existing decorators and helpers

### ✅ Task 4: Run Report v2
- [x] `telemetry/reporter.py` already implements trace-anchored reports
- [x] "stopped-because" inference already implemented
- [x] Sample reports generated (`RunReportV2_Sample.json`, `RunReportV2_Sample.md`)

### ✅ Task 5: Metrics Switch
- [x] All metrics use OTel via `telemetry/otel_metrics.py` compatibility layer
- [x] Prometheus reader configured in `observability/metrics.py`
- [x] No custom `/metrics` endpoints found (Prometheus reader serves on :9464)

### ✅ Task 6: Logging Correlation
- [x] Logging instrumentation configured in `observability/otel.py`
- [x] Tests added for trace/span ID correlation

### ✅ Task 7: Remove Legacy Telemetry
- [x] Verified no `telemetry.prom` or `telemetry.otel` imports exist
- [x] Documented current telemetry architecture

### ✅ Task 8: Tests
- [x] Unit tests for bootstrap (`tests/observability/test_bootstrap.py`)
- [x] Integration tests for spans (`tests/observability/test_tracing_e2e.py`)
- [x] Log correlation tests (`tests/logs/test_log_trace_correlation.py`)
- [x] Regression tests (`tests/test_no_legacy_telemetry.py`)

### ✅ Task 9: Documentation
- [x] Migration checklist
- [x] Sample Run Report v2 JSON
- [x] Sample Run Report v2 Markdown
- [x] Removal documentation
