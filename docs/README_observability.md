# Observability Quickstart

This guide explains how to enable telemetry for the CodeIntel MCP runtime, where
timeline JSONL files are stored, and how to summarize a session with the
diagnostics CLI.

## Enabling OpenTelemetry

Telemetry is disabled by default. Export the following variables before starting
the FastAPI app:

```bash
export CODEINTEL_TELEMETRY=1
# Optional exporters
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4318"
export OTEL_CONSOLE=1  # mirror spans to stdout for local debugging
```

When enabled, the app configures an OTLP exporter if the endpoint is set and
falls back to a console exporter when `OTEL_CONSOLE=1`. Spans cover each HTTP
request, MCP tool invocation, embedding batch, FAISS search, hybrid fusion, and
DuckDB hydration.

## Timeline Flight Recorder

Timeline events are always written locally (even when OpenTelemetry is disabled)
so that incidents can be diagnosed without remote backends.

| Variable | Description | Default |
| --- | --- | --- |
| `CODEINTEL_DIAG_DIR` | Directory for `events-YYYYMMDD.jsonl` files | `./data/diagnostics` |
| `CODEINTEL_DIAG_SAMPLE` | Sampling fraction (0–1) evaluated per request | `1.0` |
| `CODEINTEL_DIAG_MAX_BYTES` | Max file size before rotation | `10_000_000` |

Example timeline entry:

```json
{
  "ts": 1737481200.12,
  "session_id": "b3710072",
  "run_id": "6da2b139c0db46df",
  "type": "faiss.search.end",
  "name": "faiss",
  "status": "ok",
  "attrs": {
    "duration_ms": 32,
    "k": 50,
    "nprobe": 128,
    "rows": 1,
    "use_gpu": true
  }
}
```

Every event mirrors a lightweight OpenTelemetry span or span event (when
available) so JSONL and tracing can be correlated.

## Diagnostics CLI

Use the diagnostics CLI to summarize a session/run into Markdown:

```bash
python -m codeintel_rev.diagnostics.report_cli \
  --events data/diagnostics/events-20250101.jsonl \
  --session b3710072 \
  --out report.md
```

The report includes:

- Operation chain with durations and status glyphs.
- Stage durations for embeddings, FAISS, hybrid fusion, and DuckDB hydration.
- Explicit skip reasons for BM25/SPLADE channels.
- Decision events (e.g., reranker disabled, fallbacks).

Attach the Markdown to incident tickets for a copy-ready timeline of “what ran,
what skipped, and why.”

## Troubleshooting

- **No events written**: ensure `CODEINTEL_DIAG_DIR` is writable and sampling is
  non-zero.
- **Empty CLI output**: confirm you passed the correct `--session` ID (accessible
  via the `X-Session-ID` header logged by the middleware). The CLI automatically
  selects the most recent `run_id` for a session.
- **Missing OpenTelemetry spans**: verify `CODEINTEL_TELEMETRY=1` and the
  `opentelemetry-sdk` dependency is installed. Console exporter can be enabled
  with `OTEL_CONSOLE=1` to sanity-check span creation locally.
