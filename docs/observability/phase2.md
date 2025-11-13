# OpenTelemetry Phase 2 Add-On

This document summarizes the Phase 2 observability upgrades for the `codeintel_rev`
MCP server. The goal is to unlock end-to-end traces, structured run reports, and
diagnostics that remain completely optional—when OpenTelemetry dependencies or
collectors are absent the server behaves exactly as before.

---

## Quick start

1. Copy `config/otel.example.env` to a local `.env` and adjust the values for your
   collector (Tempo, Jaeger, Honeycomb, etc.).
2. Export the variables (or point your process manager at the file) and start the
   MCP server. Example:

   ```bash
   export CODEINTEL_OTEL_ENABLED=1
   export CODEINTEL_OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/traces
   export CODEINTEL_OTEL_SAMPLER=parentbased_traceidratio:0.25
   uv run fastapi dev codeintel_rev.app.main:app
   ```

3. Every request now emits an `X-Trace-Id` response header, writes a flight recorder
   JSON artifact under `DATA_DIR/runs/<date>/<session>/<run>.json`, and enriches the
   `AnswerEnvelope` with `trace_id`, `span_id`, `run_id`, and `diag_report_uri`
   (when telemetry is enabled).

Disable OTel at any point by unsetting `CODEINTEL_OTEL_ENABLED` (or setting it to `0`).
All existing Prometheus metrics and timeline artifacts remain available regardless
of the toggle.

---

## Environment knobs

| Variable | Purpose | Notes |
| --- | --- | --- |
| `CODEINTEL_OTEL_ENABLED` | Master toggle for tracing/metrics/log hooks | defaults to `0` |
| `CODEINTEL_OTEL_SERVICE_NAME` | Resource attribute applied to spans/metrics | default `codeintel-mcp` |
| `CODEINTEL_OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP HTTP endpoint for traces (and metrics when metrics endpoint unset) | include `/v1/traces` suffix |
| `CODEINTEL_OTEL_METRICS_ENDPOINT` | Optional OTLP metrics endpoint override | defaults to trace endpoint |
| `CODEINTEL_OTEL_SAMPLER` | Sampler spec (e.g., `parentbased_traceidratio:0.2`) | supports `always_on`, `always_off`, `traceidratio`, `parentbased_traceidratio` |
| `CODEINTEL_OTEL_LOGS_ENABLED` | Enables minimal logging instrumentation | default `1` |
| `CODEINTEL_OTEL_METRICS_ENABLED` | Bootstraps OTLP metric exporter | default `0` |
| `CODEINTEL_DIAG_DIR` | Legacy timeline directory (JSONL) | default `./data/diagnostics` |
| `DATA_DIR` | Base data directory (flight recorder uses `DATA_DIR/runs/...`) | default `./data` |

All variables are optional—missing values simply downgrade to no-op mode.

---

## Flight recorder output

When tracing is enabled the server registers a lightweight span processor that
captures span lifecycle events per trace and persists a compact run report:

```
DATA_DIR/runs/<YYYYMMDD>/<session_id>/<run_id>.json
```

Each JSON file contains:

* `trace_id` and root `span_id`
* `session_id`, `run_id`, status, and stop reason
* An ordered `events` array where each entry includes:
  * wall-clock timestamp (`ts`)
  * stage/component
  * duration and child span events
  * scrubbed attributes (`retrieval.*`, budgets, degradation warnings, etc.)

The MCP adapters add the file path to the response envelope as `diag_report_uri`,
allowing agents (or humans) to jump directly from an `AnswerEnvelope` to the
flight recorder output.

---

## Diagnostics & verification

* Every HTTP response now includes `X-Trace-Id`. Paste this ID into your trace
  backend to inspect the ingress span (`mcp.search.*`, readiness, capability
  detection, retrieval pipeline, Git adapters, etc.).
* When degradation occurs (FAISS fallback, warm-up warnings, etc.) the
  corresponding spans set `warn.degraded=true` and emit events describing the
  fallback reason and target.
* Disable tracing instantly via `CODEINTEL_OTEL_ENABLED=0`—the middleware, run
  reports, and Prometheus metrics all continue to work with zero configuration.

Use `docs/observability/phase2.md` as the canonical reference for these toggles
and expected artifacts when onboarding teammates or configuring CI/staging jobs.
