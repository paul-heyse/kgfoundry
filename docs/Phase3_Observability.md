# Phase 3 Observability Overview

This document captures the architecture introduced in Phase 3 of the
observability road map. The goal is to make every run narratable via
structured step events, OpenTelemetry spans, and durable run ledgers.

## Event DSL & Ledgers

* `codeintel_rev/telemetry/steps.py` defines `StepEvent` and the `emit_step`
  helper. Emitted events automatically fan out to:
  - The active OpenTelemetry span (`add_event`)
  - The per-run JSONL ledger (`data/telemetry/runs/<date>/<run_id>.jsonl`)
  - The in-memory reporter store (for HTTP `/reports/...` and CLI consumers)
* `SessionScopeMiddleware` and `tool_operation_scope` bind a `RunLedger` to the
  current context so deeper layers can emit events without plumbing parameters.

## Span Coverage & Instrumented Stages

* vLLM embeddings, FAISS ANN searches, DuckDB hydration, Git blame, and the
  hybrid retrieval pipeline now emit `StepEvent`s with sizes, durations, and
  context (model names, nprobe, channels, etc.).
* Error handlers issue `StepEvent(kind="*.error", status="failed", detail=…)`
  so ledgers capture the final reason a run stopped.

## Run Reports & CLI

* `codeintel_rev/observability/run_report.py` composes ledger-driven reports
  with stop-reason inference.
* `codeintel_rev/diagnostics/report_cli.py` exposes `codeintel diagnostics report run
  <run_id>` using Typer and the ledger API. Reports are dumped as JSON for AI
  agents or humans.
* `/admin/index/observability/run/{run_id}/report` serves the same payload via
  FastAPI, making it easy to fetch a report for a run id returned in response
  headers (`X-Run-Id`).

## File Drop Points

* Ledger artifacts live under `data/telemetry/runs/<YYYY-MM-DD>/<run_id>.jsonl`.
* CLI/HTTP reports emit Markdown & JSON under `out/run_reports/` when requested.

## Next Steps

* Add richer stop-reason heuristics (mapping error codes to remediation).
* Extend ledgers with per-stage resource identifiers (paths, index versions).
* Visualise ledgers alongside traces in a TUI for quick postmortems.
