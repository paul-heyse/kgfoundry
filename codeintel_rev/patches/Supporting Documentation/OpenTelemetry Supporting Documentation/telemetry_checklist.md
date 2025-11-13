# CodeIntel MCP — Telemetry Readiness & Run Checklist

Use this checklist before any local run (CLI or HTTP server). It is intentionally verbose so an AI agent or a human can follow it linearly.

---

## A. Repository & Artifacts

- [ ] **Repo root is correct** (env `REPO_ROOT` or default working dir).
- [ ] **SCIP index available** (`index.scip.json`), consistent with current working copy.
- [ ] **DuckDB catalog present** and readable (e.g., `duckdb_path`).
- [ ] **FAISS index exists** (CPU index path) and optional **GPU clone** logic enabled when available.
- [ ] **XTR/WARP artifacts** (if enabled) exist and paths resolve.
- [ ] **Git repository** is accessible for blame/history tools.

## B. Runtime Environment

- [ ] **Python version** meets project requirements.
- [ ] **Optional GPU** stack available (CUDA, torch, FAISS w/ GPU). If present, run the GPU doctor tool first.
- [ ] **Redis (if configured)** reachable for session scope caching.
- [ ] **Port bindings** free for the HTTP server.
- [ ] **Logging directory** exists (if file logging is enabled).

## C. Telemetry & Diagnostics (enable-by-config)

- [ ] **Structured logging** to stdout (JSON) with log level in env (`LOG_LEVEL`).
- [ ] **Timeline event bus** enabled (per-request, per-stage) for CLI and HTTP flows.
- [ ] **Span correlation**: a single `session_id` flows across CLI steps or HTTP tool calls.
- [ ] **Metrics** (Prometheus/OpenMetrics) exporter enabled if desired.
- [ ] **Run-report writer** configured: JSON + Markdown snapshots per run are persisted to an artifacts folder.

## D. HTTP Server Wiring (MCP)

- [ ] **Middleware for context** is active (sets `ApplicationContext` in contextvar).
- [ ] **Session scope middleware** is active and generates/extracts `X-Session-ID`.
- [ ] **Capability-gated tool registration** (semantic/symbols) respects available artifacts and degrades gracefully.
- [ ] **Readiness** endpoint (or probe) confirms indexes and model connections before serving.
- [ ] **Problem Details** mapping of exceptions emits structured error envelopes with context.

## E. CLI Pipeline (Index/Enrichment)

- [ ] **Scan / enrich** entrypoint selected (full or incremental run).
- [ ] **Per-stage timeline** enabled: document load → symbol extraction → enrichment → graph build → write-out.
- [ ] **Artifacts** (parquet, graphs) written under a date/commit-scoped directory.

## F. Pre-Run Sanity

- [ ] **Run configuration snapshot** captured to the run folder (env, versions, paths).
- [ ] **Dry-run** or **probe** step completes without fatal errors.
- [ ] **Degraded-mode warnings** acknowledged (e.g., SPLADE/BM25 disabled).

## G. Post-Run Outputs

- [ ] **Run report** JSON and Markdown generated.
- [ ] **Top warnings** summarized with suggested actions.
- [ ] **Artifacts inventory** attached (paths, sizes, counts).