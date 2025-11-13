# Phase-0 Telemetry Architecture

> Diagnostic tracing, metrics, structured logging, and run reports for the CodeIntel MCP server.

## Signals at a Glance

| Signal      | What we emit                                                                                     | Default exporter                                   |
|-------------|--------------------------------------------------------------------------------------------------|----------------------------------------------------|
| Traces + events | Span per tool (`mcp.request`) plus stage spans (`search.embed`, `search.faiss`, `catalog.hydrate`, `git.blame`, …). Timeline events remain append-only JSONL. | OTLP HTTP when `OTEL_EXPORTER_OTLP_ENDPOINT` is set, otherwise console |
| Metrics     | Prometheus counters/histograms: `codeintel_runs_total{status,tool}`, `codeintel_mcp_request_latency_seconds{tool,status}`, `codeintel_search_stage_latency_seconds{stage}`. | Exposed via `/metrics` when `PROMETHEUS_ENABLED=1` |
| Logs        | JSON logs with `session_id`, `run_id`, `request_tool`, and stage notes. Optional OTLP log exporter piggy-backs on the same endpoint config. | Stdout JSON; OTLP when enabled                     |
| Run reports | In-memory reconstruction of sampled timelines + checkpoints. Available as JSON or Markdown.      | `GET /reports/{session_id}` and `/reports/{session_id}.md`          |

Telemetry is **safe-by-default**: if OpenTelemetry packages or OTLP endpoints are missing, the code falls back to console exporters and JSON logging only.

## Configuration Cheatsheet

| Variable | Default | Effect |
|----------|---------|--------|
| `TELEMETRY_ENABLED` | `1` | Master switch for tracing + metrics + logs. Set to `0` to disable everything. |
| `OTEL_SERVICE_NAME` | `codeintel-mcp` | `service.name` resource attribute. |
| `OTEL_SERVICE_VERSION` | package version | Overrides `service.version` resource attribute. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | When set (`http://otel-collector:4318`), enables OTLP/HTTP exporters for traces, metrics, and logs. |
| `OTEL_EXPORTER_OTLP_INSECURE` | `1` | Allow HTTP (no TLS) connections to OTLP endpoint. |
| `PROMETHEUS_ENABLED` | `1` | Registers the `/metrics` route and emits Prometheus counters/histograms. |
| `RUN_REPORT_RETENTION` | `100` | Number of session/run timelines retained in-memory for retrospective reports. |

### Quickstart

```bash
# Local console exporters only
export TELEMETRY_ENABLED=1
uv run fastapi dev codeintel_rev.app.main:app

# Ship all signals to a local collector
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"
export OTEL_SERVICE_NAME="codeintel-mcp-dev"
uv run fastapi dev codeintel_rev.app.main:app
```

## Run Reports

Every sampled session captures:

1. Ordered operations + steps (`embed → faiss → bm25 → splade → rrf → hydrate`)
2. Decisions and degradations (budget gates, channel skips, fallbacks)
3. Checkpoints emitted by decorators (`report.checkpoint` events)
4. Errors and partial runs (stop reason recorded even for non-fatal aborts)

Endpoints:

```bash
# JSON
curl -s http://localhost:8080/reports/SESSION_ID | jq

# Markdown (copy/paste friendly)
curl -s http://localhost:8080/reports/SESSION_ID.md
```

Sample JSON snippet:

```json
{
  "session_id": "abc123",
  "run_id": "5f1c0e2cbe844b31955d19b5e0dd7dc9",
  "status": "complete",
  "operations": [
    {
      "name": "mcp.tool.semantic_search",
      "duration_ms": 154,
      "attrs": {"tool": "semantic_search", "session_id": "abc123"}
    }
  ],
  "steps": [
    {"name": "search.embed", "duration_ms": 17, "attrs": {"mode": "http", "n_texts": 1}},
    {"name": "search.faiss", "duration_ms": 21, "attrs": {"k": 20, "nprobe": 24}},
    {"name": "search.rrf_fuse", "duration_ms": 3, "attrs": {"rrf_k": 60}}
  ],
  "decisions": [{"name": "hybrid.query_profile", "attrs": {"channels": ["semantic","bm25"]}}],
  "warnings": [],
  "errors": [],
  "checkpoints": [
    {"stage": "search.embed", "ok": true},
    {"stage": "search.faiss", "ok": true},
    {"stage": "catalog.hydrate", "ok": true}
  ],
  "telemetry": {"session_id": "abc123", "run_id": "5f1c0e2cbe844b31955d19b5e0dd7dc9"}
}
```

Markdown output mirrors the same content for quick incident sharing.

## Metrics Reference

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `codeintel_runs_total` | Counter | `tool`, `status` | MCP tool invocations by result (`complete`, `error`). |
| `codeintel_run_errors_total` | Counter | `tool`, `error_code` | Error category counts derived from stop reason. |
| `codeintel_mcp_request_latency_seconds` | Histogram | `tool`, `status` | Wall-clock latency per tool invocation. |
| `codeintel_search_stage_latency_seconds` | Histogram | `stage` | Stage latency for `search.embed`, `search.faiss`, `search.bm25`, `catalog.hydrate`, `git.blame`, etc. |
| `codeintel_runs_partial_total` | Counter (derived) | `tool` | Incremented when a run ends before hydrate/response. |

Prometheus scraping:

```
GET /metrics
```

Enable/disable via `PROMETHEUS_ENABLED`.

## Span & Event Taxonomy

| Span name | Attributes | Notes |
|-----------|------------|-------|
| `mcp.request` | `request_tool`, `session.id`, `run.id`, `args.hash` | Created in `tool_operation_scope`. |
| `search.embed` | `mode`, `n_texts`, `dim` | Wraps `VLLMClient.embed_batch` (sync+async). |
| `search.faiss` | `k`, `nprobe`, `use_gpu` | Wraps dual-index FAISS search/merge. |
| `search.{channel}` | `channel`, `limit` | Emitted per hybrid channel (semantic, bm25, splade, warp, etc.). |
| `search.rrf_fuse` | `rrf_k`, `channels` | Covers fusion/pooling logic. |
| `catalog.hydrate` | `op`, `asked_for`, `returned` | DuckDB hydration and scope filtering. |
| `git.blame` / `git.file_history` | `path`, `range|limit` | Git adapters. |

Timeline events (JSONL) continue to be sampled and mirrored into span events so console exporters still tell the story even without OTLP.

## Logs

`install_structured_logging()` applies the shared JSON formatter. Fields automatically included:

* `session_id`, `run_id`, `request_tool`, `request_stage`
* Standard message / level / timestamp

To ship logs via OTLP:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"
export TELEMETRY_ENABLED=1
```

## Operator Runbook

1. **Capture the Session ID** – adapters return `telemetry.session_id` + `telemetry.run_id`. Keep them in tickets.
2. **Fetch the run report** – `curl /reports/{session_id}` for JSON or `.md` for collaborative debugging.
3. **Inspect checkpoints** – each stage is marked `ok` or `error`. Partial runs show `status=partial` with `stop_reason`.
4. **Check `/metrics`** – look for spikes in `codeintel_run_errors_total{error_code="faiss"}` or latency histograms.
5. **Trace export (optional)** – point OTLP at your collector to feed Jaeger/Tempo/Elastic.

This baseline delivers **high-signal diagnostics without introducing merge gates**. Add collectors, dashboards, or alerting on top of these primitives as needed.
