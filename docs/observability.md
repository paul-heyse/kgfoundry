# Observability Guide

CodeIntel MCP now emits rich telemetry across HTTP and CLI entrypoints. This document
captures the key surfaces and how to use them locally.

## OpenTelemetry bootstrap

- `codeintel_rev.observability.otel.init_telemetry(service_name, service_version)` wires the
  `opentelemetry` SDK when `CODEINTEL_TELEMETRY=1`.
- `instrument_fastapi(app)` and `instrument_httpx()` attach auto-instrumentation.
- Logging correlation (`LoggingInstrumentor`) is enabled by default; disable by passing
  `enable_logging_instrumentation=False` to `init_telemetry`.

All helpers degrade to no-ops when the SDK is missing or the environment flag is unset.

## Timeline bindings

- HTTP requests: `SessionScopeMiddleware` now creates a per-request `Timeline`, binds it to the
  request context, and stamps metadata (`kind=http`, route, method, session/run IDs).
- CLI: `codeintel_rev.cli.main()` creates a root `Timeline` (`kind=cli`) for every invocation so
  instrumentation inside indexing/enrichment runs produces events and run reports.

## Stage-level hybrid telemetry

- `HybridSearchEngine.search()` emits scoped steps for `embed`, `search.faiss`, `search.bm25`,
  `search.splade`, `fusion.rrf/pool`, and `channel.run/channel.skip` events. Stage timings are
  mirrored in `MethodInfo.stages`.
- VLLM embeddings wrap `Timeline.step("embed.vllm", …)` and `as_span("embed.vllm", …)` so vector
  generation is auditable.
- DuckDB connections proxy `execute()` to emit `sql.exec` steps with optional SQL previews when
  `DuckDBConfig.log_queries` is enabled.

## Run reports

- `render_run_report(timeline, out_dir=…)` writes JSON and Markdown artifacts under
  `data/observability/runs/<run_id>.{json,md}` (default directory configurable via `out_dir`).
- HTTP tool executions automatically render reports (success or failure) via
  `tool_operation_scope`. CLI runs call the same writer at process exit.
- The most recent artifact is tracked via `latest_run_report()` and exposed as MCP tool
  `report:latest_run`, which returns paths plus a summary snippet.

## Inspecting artifacts

- To list run reports: `ls data/observability/runs`.
- JSON schema: `codeintel.telemetry/run-report@v0`.
- Markdown summary includes session/run IDs, status, first error, and the ordered timeline
  (operations, decisions, warnings).

## Quick tips

- Set `CODEINTEL_DIAG_DIR` to isolate timeline JSONL output while developing.
- Use the MCP tool `report:latest_run` to share the latest report path with other agents/clients.
- `duckdb` and `vllm` spans appear even when OTel exporters are absent; they collapse to cheap
  no-ops unless telemetry is enabled.
