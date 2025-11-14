# Telemetry Phase 4 Notes

This document captures the developer-facing details for the Phase 4 telemetry work.

## Surfaces Delivered

- **HTTP run exports** – `/reports/{session}` now emits JSON, Markdown, and Mermaid graphs (aliases exposed under `/runs/...`). The Mermaid endpoint (`.mmd`) can be pasted directly into editors that understand Mermaid diagrams to visualize stage progression and stop points.
- **CLI parity** – `codeintel telemetry report --format {json,md,mmd}` mirrors the HTTP exports but operates directly on timeline JSONL artifacts, making it easy to inspect runs from CI or local sandboxes. `codeintel telemetry runpack` produces flight-recorder zip archives with reports, budgets, and sanitized context snapshots.
- **Runpacks** – Every MCP adapter failure attaches a `runpack_path` to the Problem Details envelope. Operators can also generate runpacks on demand through the CLI.
- **Detectors & hints** – The run reporter emits structured hints (`report["hints"]`) that capture common misconfigurations (e.g., RM3 enabled while sparse channels are skipped, FAISS falling back to CPU, vLLM micro-batches).
- **Mermaid graphs** – Both `RunReport` and `TimelineRunReport` can be rendered as `graph TD` diagrams for docs, dashboards, or markdown previews.

## Usage Examples

```bash
# JSON report
codeintel telemetry report sess-123 --run-id run-abc

# Markdown version for sharing in docs
codeintel telemetry report sess-123 --run-id run-abc --format md

# Mermaid graph to paste into the Agent Portal
codeintel telemetry report sess-123 --run-id run-abc --format mmd > run.mmd

# Generate a runpack after an MCP failure (path is logged in the error envelope)
codeintel telemetry runpack sess-123 --run-id run-abc
```

## Operator Notes

- Mermaid exports intentionally preserve every checkpoint in order; if a stage never emitted a checkpoint the graph will highlight the missing edge, making "stopped-because" reasoning quick.
- Runpack archives live alongside timeline files (`CODEINTEL_DIAG_DIR/runpacks/{session}`) and can be safely shared since they redact obvious secrets.
- Tail-sampling and OTel collector recommendations are tracked in `ops/otel/collector-phase4.yaml`; ensure the `codeintel.*` attributes referenced there are preserved in spans/logs when adding new instrumentation.
