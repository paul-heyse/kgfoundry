# Execution Ledger

The execution ledger is a deterministic run log for every MCP tool request. It
records **what actually happened** across the retrieval stack and ties each
operation to OpenTelemetry spans so failures (or partial runs) are narratable.

## Why it exists

- Provide a single trace that explains where a request stopped and why.
- Capture stage-level timings (embed → pool/search → fuse → hydrate → rerank → envelope).
- Export self-contained Run Reports so operators can triage issues without
  digging through logs.

## Runtime configuration

Environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `LEDGER_ENABLED` | `true` | Disable to skip ledger writes entirely. |
| `LEDGER_MAX_RUNS` | `512` | Size of the in-process ring buffer. Oldest runs are evicted first. |
| `LEDGER_FLUSH_PATH` | unset | When provided, every run is mirrored to the path as newline-delimited JSON. |
| `LEDGER_INCLUDE_REQUEST_BODY` | `false` | Include raw request payloads in ledger entries (off by default to keep payloads scrubbed). |

## Accessing Run Reports

The FastAPI app exposes two diagnostics routes once the ledger is enabled:

```text
GET /diagnostics/run_report/{run_id}
GET /diagnostics/run_report/{run_id}.md
```

The JSON variant returns the structured payload produced by
`codeintel_rev.observability.execution_ledger.build_run_report`. The Markdown
variant renders the same payload for quick sharing (for example in Slack or an
incident ticket).

Example usage (assuming `RUN_ID` was returned in the MCP envelope):

```bash
curl -s localhost:8000/diagnostics/run_report/$RUN_ID | jq '.stage_durations_ms'
```

Sample outputs (one successful and one interrupted run) live under
`examples/diagnostics/`:

- [`examples/diagnostics/run_success.json`](../../examples/diagnostics/run_success.json)
- [`examples/diagnostics/run_success.md`](../../examples/diagnostics/run_success.md)
- [`examples/diagnostics/run_partial.json`](../../examples/diagnostics/run_partial.json)
- [`examples/diagnostics/run_partial.md`](../../examples/diagnostics/run_partial.md)

These snapshots mirror what the new endpoints return.

## Developer workflow

```python
from codeintel_rev.observability import execution_ledger

run_id = execution_ledger.begin_run(tool="mcp.tool:semantic", session_id="demo", run_id="demo")
with execution_ledger.step(stage="embed", op="demo", component="tests"):
    ...  # perform work
execution_ledger.record("run.end", stage="envelope", component="tests", results=3)
execution_ledger.end_run(status="ok")

payload = execution_ledger.build_run_report(run_id)
print(payload["stages_reached"])  # ["embed", "envelope"]
```

The ledger does not block the request path—write failures are swallowed after
logging so diagnostics never become the outage.

## Troubleshooting

- **Missing run report**: the run may have been evicted (older than
  `LEDGER_MAX_RUNS`) or `LEDGER_ENABLED` is off. Check the process logs for the
  `execution_ledger.ready` event emitted at startup.
- **No envelope data**: ensure adapters call `ledger_step` or `record` when
  building their envelopes. Semantic and semantic_pro already do this; mirror
  the pattern for new tools.
