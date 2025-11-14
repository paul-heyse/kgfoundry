# OTel Migration Checklist

This checklist captures the current legacy telemetry surfaces that must be replaced and the
hot-path seams that require new OpenTelemetry spans/events. It will be updated as the
migration progresses.

## Legacy import inventory

### Modules importing `codeintel_rev.telemetry.prom`

| Path | Symbols | Notes |
| --- | --- | --- |
| `codeintel_rev/app/main.py` | `build_metrics_router` | Legacy `/metrics` router still mounted on the FastAPI app. |
| `codeintel_rev/mcp_server/telemetry.py` | `observe_request_latency` | Records MCP tool durations using the Prometheus shim. |
| `codeintel_rev/retrieval/gating.py` | `GATING_DECISIONS_TOTAL`, `RRFK`, `QUERY_AMBIGUITY` | Gating logic writes counters/histograms directly through the shim. |
| `codeintel_rev/io/vllm_client.py` | `EMBED_BATCH_SIZE`, `EMBED_LATENCY_SECONDS` | Embedding client records latency/batch metrics via legacy helpers. |
| `codeintel_rev/io/faiss_manager.py` | `FAISS_SEARCH_LATENCY_SECONDS` | FAISS search timings recorded with shim histogram. |
| `codeintel_rev/io/xtr_manager.py` | `XTR_SEARCH_LATENCY_SECONDS` | XTR manager emits latency histogram samples through shim. |
| `codeintel_rev/telemetry/decorators.py` | `record_stage_latency` | Decorators emit stage timing metrics with shim helper. |
| `codeintel_rev/telemetry/reporter.py` | `record_run`, `record_run_error` | Run-report bookkeeping increments Prometheus counters. |
| `codeintel_rev/telemetry/__init__.py` | Multiple re-exports | Top-level telemetry namespace still re-exports shim symbols. |
| `tests/telemetry/test_prometheus_router.py` | `build_metrics_router` | Test coverage for now-deprecated router. |

### Modules importing `codeintel_rev.telemetry.otel`

| Path | Symbols | Notes |
| --- | --- | --- |
| `codeintel_rev/telemetry/__init__.py` | `install_otel` | Re-export of the legacy bootstrap entry point. |
| `codeintel_rev/telemetry/logging.py` | `_env_flag`, `build_resource` | Structured logging bootstrap depends on helpers inside the legacy module. |

### Direct `prometheus_client` usage

| Path | Usage | Notes |
| --- | --- | --- |
| `codeintel_rev/observability/otel.py` | `start_http_server` | Starts embedded `/metrics` endpoint; must move under `observability/metrics.py`. |
| `tests/codeintel_rev/test_observability_common.py` | Collector fixtures | Unit test uses stubbed registry helpers. |
| `tests/conftest.py` | `CollectorRegistry` fixture | Shared test fixture wires Prometheus registry. |
| `tests/telemetry/test_prometheus_router.py` | Router assertions | Exercises the `build_metrics_router` shim. |
| `tests/kgfoundry_common/test_prometheus_metrics.py` | Direct import | Validates kgfoundry_common Prom helpers; not part of MCP app but noted for completeness. |
| `tests/codeintel_rev/retrieval/test_telemetry.py` | Collector/metrics asserts | Exercises retrieval metrics path. |
| `src/kgfoundry_common/prometheus.py` | Compatibility layer | Shared Prom wrapper still depends on upstream client. |

## Hot-path span inventory

| Path | Operations requiring spans/events | Notes |
| --- | --- | --- |
| `codeintel_rev/mcp_server/adapters/semantic.py` | Tool SERVER span, `embed → gather_channels → pool → fuse → recency_boost → hydrate → rerank → envelope` | Main semantic adapter covering embeddings, FAISS, DuckDB hydration. |
| `codeintel_rev/mcp_server/adapters/semantic_pro.py` | Same stage coverage as semantic adapter plus pro-only reranker toggles | Additional pro features require consistent spans. |
| `codeintel_rev/mcp_server/adapters/text_search.py` | SERVER span for BM25/SPLADE-only flow | Needs events for gather, pool, and envelope creation. |
| `codeintel_rev/mcp_server/adapters/history.py` | SERVER span for history tool | Should emit stages for query normalization, filtering, and hydration. |
| `codeintel_rev/retrieval/hybrid.py` | INTERNAL spans for `gather_channels`, `pool`, `fuse`, `recency_boost`, `hydrate`, `rerank` | Heart of retrieval pipeline; currently only timeline hooks exist. |
| `codeintel_rev/retrieval/mcp_search.py` | INTERNAL span bridging MCP adapter to hybrid search | Needs events for scope parsing and channel fan-out. |
| `codeintel_rev/retrieval/gating.py` | INTERNAL span for budget/routing decisions | Capture `top_k`, per-channel depths, and gating heuristics. |
| `codeintel_rev/retrieval/fusion/weighted_rrf.py` | INTERNAL span for fusion math | Attach channel weights, RRF k, and candidate counts. |
| `codeintel_rev/io/vllm_client.py` | CLIENT span around HTTP/in-proc embed calls | Include model/mode attributes, batch size, and timings. |
| `codeintel_rev/io/duckdb_manager.py` | INTERNAL spans for DuckDB queries | Record SQL size, row count, and hydration timings. |
| `codeintel_rev/io/git_client.py` | CLIENT spans for blame/history/diff calls | Need attributes for `git.op`, file path, and optional line range. |

These inventories serve as the baseline for removing the legacy telemetry shims and inserting
the required OpenTelemetry spans/metrics.
