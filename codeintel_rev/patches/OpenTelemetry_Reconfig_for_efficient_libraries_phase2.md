Below is a **repo‑specific, no‑shims migration plan** that finalizes your OpenTelemetry re‑architecture and **fully decommissions the legacy Prometheus plumbing**. It includes:

* a tight narrative of what to change and why (repo‑grounded),
* concrete **code diffs** (unified patches) for each file,
* a small **codemod/check** to prevent regressions, and
* **end‑to‑end tests** that validate traces/metrics are emitted after the switch.

Where I assert file names or current behavior, I cite your repo map and SCIP index; e.g., `telemetry/prom.py` and `observability/otel.py` exist and are treated as re‑export hubs today, and `gating.py` still imports counters from `telemetry.prom`.   

---

## What this phase delivers

* **One telemetry surface (OTel)** for traces, metrics, and logs.
* **No custom `/metrics` endpoint** and **no direct Counters/Histograms** from `prometheus_client` anywhere—**only** OTel Metrics + **PrometheusMetricReader**.
* **Import hygiene enforced**: if any file references `codeintel_rev.telemetry.prom` or `prometheus_client` (beyond the embedded HTTP server helper), tests fail.
* **E2E validation** that:

  * vLLM embed and FAISS search **latency histograms** publish via Prometheus scrape (OTel reader),
  * FastAPI server spans show operation steps (`gather_channels`, `fuse`, `hydrate`) and MCP tool spans, and
  * “runpack”/timeline/report features remain intact (they sit alongside OTel).   

> This plan assumes you already applied the prior “reconfig for efficient libraries” foundation (distro/CLI optional, OTel Prom reader), as documented in your internal guide. I keep the same names and metric intentions already present in the tree (e.g., **gating**, **FAISS**, **DuckDB**, **vLLM**).  

---

## Step‑by‑step plan (no deprecation shims)

### 1) Own the OTel Metrics provider and Prometheus scrape **in one place**

Centralize the MeterProvider + PrometheusMetricReader in `observability/metrics.py`. This becomes the only place we touch Prometheus HTTP server startup (optional) and where we add Views/buckets. (Your repo already carries this module.) 

> Rationale: Replace the custom `/metrics` route found in `telemetry/prom.py` and the direct use of `prometheus_client.generate_latest` with **OTel’s Prometheus reader**. After this, no code should import `telemetry.prom` for instruments. 

**Diff — `codeintel_rev/observability/metrics.py` (augment / replace content as needed):**

```diff
*** a/codeintel_rev/observability/metrics.py
--- b/codeintel_rev/observability/metrics.py
@@
+from __future__ import annotations
+import os
+from opentelemetry import metrics
+from opentelemetry.sdk.metrics import MeterProvider, View
+from opentelemetry.sdk.metrics.export import ExplicitBucketHistogramAggregation
+from opentelemetry.sdk.resources import Resource
+try:
+    # OTel → Prom scrape; this registers a collector on the default Prom registry
+    from opentelemetry.exporter.prometheus import PrometheusMetricReader
+    from prometheus_client import start_http_server  # only to serve /metrics
+except Exception:  # pragma: no cover - optional deps
+    PrometheusMetricReader = None  # type: ignore
+    start_http_server = None       # type: ignore
+
+_METRICS_INSTALLED = False
+
+def install_metrics_provider(resource: Resource) -> None:
+    """
+    Install a global OTel MeterProvider with Prometheus reader + Views.
+    Idempotent. If exporter packages are missing, this is a safe no-op.
+    """
+    global _METRICS_INSTALLED
+    if _METRICS_INSTALLED or PrometheusMetricReader is None:
+        return
+
+    # ---- Sane default buckets (seconds) for latency
+    req_ms_buckets = [0.001, 0.005, 0.010, 0.025, 0.050, 0.100, 0.250, 0.500, 1.0, 2.5]
+    views = [
+        View(
+            instrument_name="embed_latency_seconds",
+            aggregation=ExplicitBucketHistogramAggregation(req_ms_buckets),
+        ),
+        View(
+            instrument_name="faiss_search_latency_seconds",
+            aggregation=ExplicitBucketHistogramAggregation(req_ms_buckets),
+        ),
+        View(
+            instrument_name="duckdb_execute_seconds",
+            aggregation=ExplicitBucketHistogramAggregation(req_ms_buckets),
+        ),
+    ]
+
+    reader = PrometheusMetricReader(prefix="codeintel")
+    provider = MeterProvider(resource=resource, metric_readers=[reader], views=views)
+    metrics.set_meter_provider(provider)
+
+    # Optionally start an embedded /metrics server (Prometheus scrapes here)
+    if start_http_server is not None:
+        port = int(os.getenv("PROMETHEUS_PORT", "9464"))
+        addr = os.getenv("PROMETHEUS_ADDR", "0.0.0.0")
+        start_http_server(port=port, addr=addr)
+
+    _METRICS_INSTALLED = True
```

### 2) Wire Metrics provider during OTel bootstrap

Ensure `observability/otel.py` (your SDK setup layer) installs the metrics provider above. This keeps one bootstrap path. (Your tree already contains `observability/otel.py`.) 

**Diff — `codeintel_rev/observability/otel.py`:**

```diff
*** a/codeintel_rev/observability/otel.py
--- b/codeintel_rev/observability/otel.py
@@
 from opentelemetry import trace
 from opentelemetry.sdk.resources import Resource
 from opentelemetry.sdk.trace import TracerProvider
 from opentelemetry.sdk.trace.export import BatchSpanProcessor
+from .metrics import install_metrics_provider
@@
 def init_otel(*, service_name: str, service_version: str | None = None) -> None:
     """Install OTel providers and exporters. Safe to call once at startup."""
-    resource = Resource.create({"service.name": service_name, "service.version": service_version or "dev"})
+    resource = Resource.create({"service.name": service_name, "service.version": service_version or "dev"})
     provider = TracerProvider(resource=resource)
     trace.set_tracer_provider(provider)
     # Exporters/processors bound by env or elsewhere in this module...
     provider.add_span_processor(BatchSpanProcessor(_make_trace_exporter()))
+
+    # Always install metrics provider (Prometheus reader + Views)
+    install_metrics_provider(resource)
```

> Note: `_make_trace_exporter()` is assumed to exist from your previous phase; if not, keep your existing env‑driven exporter code here. The “reconfig” doc in your repo shows this pattern and the env knobs you standardised on. 

### 3) **Delete** the legacy Prometheus endpoint and in‑tree instruments

* Remove the file that exposes `/metrics` and the direct `prometheus_client.generate_latest` path; this file is marked as a **FastAPI** surface and a **reexport hub** in your repo map. 
* Also delete the **legacy** `telemetry/otel.py` (duplicate bootstrap surface) to avoid two sources of truth. 

**Diff — delete legacy files:**

```diff
*** a/codeintel_rev/telemetry/prom.py
--- /dev/null
@@
-# removed: replaced by OTel PrometheusMetricReader in observability/metrics.py
```

```diff
*** a/codeintel_rev/telemetry/otel.py
--- /dev/null
@@
-# removed: single bootstrap lives in observability/otel.py
```

> Why safe: your active metrics definitions already moved toward OTel (see `metrics/registry.py`), and we will re‑point all remaining imports to the registry. 

### 4) Consolidate **all instruments** in `metrics/registry.py` and **stop importing** from `telemetry.prom`

Your `retrieval/gating.py` still imports counters/histograms from `telemetry.prom`—we’ll switch it to the canonical registry. 

**Diff — `codeintel_rev/metrics/registry.py` (augment):**

```diff
*** a/codeintel_rev/metrics/registry.py
--- b/codeintel_rev/metrics/registry.py
@@
-from opentelemetry import metrics
+from opentelemetry import metrics
 meter = metrics.get_meter("codeintel_rev")
 
-# existing instruments ...
+# ---- Gating & retrieval
+GATING_DECISIONS_TOTAL = meter.create_counter(
+    "gating_decisions_total",
+    description="Number of gating decisions made",
+)
+RRF_K = meter.create_histogram(
+    "gating_rrf_k",
+    description="Chosen RRF k parameter per run",
+)
+QUERY_AMBIGUITY = meter.create_histogram(
+    "query_ambiguity",
+    description="Heuristic ambiguity score for a query",
+)
+
+# ---- Embeddings / vLLM
+EMBED_LATENCY_SECONDS = meter.create_histogram(
+    "embed_latency_seconds",
+    description="Latency for embed_batch calls",
+    unit="s",
+)
+EMBED_BATCH_SIZE = meter.create_histogram(
+    "embed_batch_size",
+    description="Batch size distribution for embed_batch",
+)
+
+# ---- FAISS / search
+FAISS_SEARCH_LATENCY_SECONDS = meter.create_histogram(
+    "faiss_search_latency_seconds",
+    description="Latency of FAISS search() and search_with_refine()",
+    unit="s",
+)
```

### 5) Re‑point **gating** and **hot paths** to the registry instruments

**Diff — `codeintel_rev/retrieval/gating.py`:**

```diff
*** a/codeintel_rev/retrieval/gating.py
--- b/codeintel_rev/retrieval/gating.py
@@
-from codeintel_rev.telemetry.prom import GATING_DECISIONS_TOTAL, RRFK, QUERY_AMBIGUITY
+from codeintel_rev.metrics.registry import GATING_DECISIONS_TOTAL, RRF_K, QUERY_AMBIGUITY
@@
-    RRFK.record(k)
+    RRF_K.record(k)
@@
-    QUERY_AMBIGUITY.record(score)
+    QUERY_AMBIGUITY.record(score)
@@
-    GATING_DECISIONS_TOTAL.add(1, {"class": klass, "rm3": str(rm3)})
+    GATING_DECISIONS_TOTAL.add(1, {"class": klass, "rm3": str(rm3)})
```

> This module is clearly present and described; the change just moves the import to OTel instruments. 

**Diff — `codeintel_rev/io/vllm_client.py` (wrap embed latency + batch):**

```diff
*** a/codeintel_rev/io/vllm_client.py
--- b/codeintel_rev/io/vllm_client.py
@@
+import time
+from codeintel_rev.metrics.registry import EMBED_LATENCY_SECONDS, EMBED_BATCH_SIZE
@@
     async def embed_batch(self, texts: list[str]) -> list[list[float]]:
-        # existing logic...
+        start = time.perf_counter()
+        try:
+            out = await self._impl.embed_batch(texts)  # existing call
+            return out
+        finally:
+            dur = time.perf_counter() - start
+            EMBED_LATENCY_SECONDS.record(dur, {"client": self.mode, "model": self.model})
+            EMBED_BATCH_SIZE.record(len(texts), {"client": self.mode, "model": self.model})
```

(Your vLLM client already exists with async batching hooks; we only add OTel metrics at the seam you already expose. The FAISS and hybrid engines similarly have well‑defined seams for timing/telemetry.) 

**Diff — `codeintel_rev/io/faiss_manager.py` (search latency hist):**

```diff
*** a/codeintel_rev/io/faiss_manager.py
--- b/codeintel_rev/io/faiss_manager.py
@@
+import time
+from codeintel_rev.metrics.registry import FAISS_SEARCH_LATENCY_SECONDS
@@
     def search(self, query: NDArrayF32, k: int) -> list[tuple[int, float]]:
-        # existing logic...
+        t0 = time.perf_counter()
+        try:
+            return self._search_impl(query, k)  # whatever calls into FAISS
+        finally:
+            FAISS_SEARCH_LATENCY_SECONDS.record(time.perf_counter() - t0, {"impl": "ann"})
@@
     def search_with_refine(self, query: NDArrayF32, *, k: int, catalog: DuckDBCatalog, config: RefineSearchConfig | None = None) -> list[SearchHit]:
-        # existing logic...
+        t0 = time.perf_counter()
+        try:
+            return self._search_with_refine_impl(query, k=k, catalog=catalog, config=config)
+        finally:
+            FAISS_SEARCH_LATENCY_SECONDS.record(time.perf_counter() - t0, {"impl": "ann+refine"})
```

(Your `search_with_refine` is explicitly documented in the SCIP index; the histogram above buckets via the Views we installed.) 

### 6) Remove legacy FastAPI `/metrics` wiring (if mounted)

If `app/main.py` or a router mounted the bespoke `/metrics`, drop it now (the scrape endpoint is served by `PrometheusMetricReader` on `:9464`).

**Diff — `codeintel_rev/app/main.py` (illustrative):**

```diff
*** a/codeintel_rev/app/main.py
--- b/codeintel_rev/app/main.py
@@
-# from codeintel_rev.telemetry.prom import build_metrics_router
@@
-# app.include_router(build_metrics_router(), prefix="")
+# Prometheus scrape is served by the OTel reader on PROMETHEUS_PORT (default 9464)
```

(Your repo map marks `telemetry/prom.py` as a FastAPI component; after deletion, no mount must remain.) 

### 7) Keep the **run‑reports** and **runpack** features as‑is

These remain out‑of‑band artifacts you already generate; no changes are required for this step. (They are useful companions to OTel traces for “where did the run stop and why.”) 

---

## Regression prevention (no legacy paths)

**Add test to block regressions**: if any file imports `codeintel_rev.telemetry.prom` or `prometheus_client` (beyond the server helper inside `observability/metrics.py`), the test fails.

**New — `tests/test_no_legacy_telemetry.py`:**

```python
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1] / "codeintel_rev"

def _python_files():
    for p in ROOT.rglob("*.py"):
        if "observability/metrics.py" in str(p):
            continue  # allowed to import prometheus_client.start_http_server
        yield p

def test_no_legacy_prometheus_client_imports():
    banned = {"prometheus_client", "codeintel_rev.telemetry.prom"}
    offenders = []
    for py in _python_files():
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    if n.name in banned:
                        offenders.append((py, n.name))
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod in banned:
                    offenders.append((py, mod))
    assert not offenders, f"Legacy telemetry imports found: {offenders}"
```

---

## End‑to‑end tests

### A. **Traces** appear for FastAPI/MCP requests

We use an in‑memory span exporter to validate that calling a lightweight endpoint yields spans. Your server code exposes health/readiness and semantic tool routes (see the MCP server modules referenced below).  

**New — `tests/test_tracing_e2e.py`:**

```python
import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import InMemorySpanExporter, SimpleSpanProcessor

from codeintel_rev.app.main import app  # your FastAPI app

@pytest.fixture(scope="module")
def memory_exporter():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    yield exporter
    exporter.clear()

def test_readyz_traces(memory_exporter):
    client = TestClient(app)
    resp = client.get("/readyz")  # present in your app
    assert resp.status_code == 200
    spans = memory_exporter.get_finished_spans()
    # At least one SERVER span from FastAPI auto-instrumentation (if enabled in env)
    assert len(spans) >= 1
```

### B. **Metrics** scrape via OTel Prometheus reader

We hit the reader’s HTTP server (default `:9464`) and look for the instruments installed earlier.

**New — `tests/test_metrics_e2e.py`:**

```python
import os
import time
import urllib.request

def test_prometheus_scrape_contains_codeintel_metrics():
    # Metrics server started by observability.metrics.install_metrics_provider
    port = int(os.getenv("PROMETHEUS_PORT", "9464"))
    # Give provider a moment to install at app import time
    time.sleep(0.5)
    raw = urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5).read().decode("utf-8")
    # Look for any of the instruments we created
    assert "codeintel_embed_latency_seconds_bucket" in raw or "codeintel_faiss_search_latency_seconds_bucket" in raw
```

> (If you prefer not to rely on the global server in tests, you can set a test‑specific port via `PROMETHEUS_PORT` and import the app once to trigger OTel bootstrap.)

### C. **Functional hot path smoke** (optional but valuable)

Drive a small semantic search through the adapter and verify:

* a FAISS search span exists,
* the **stage records** array is populated (you already maintain it in `HybridSearchEngine#_gather_channel_hits`), and
* at least one of the FAISS/embedding metrics appears in the scrape. 

(If building a full FAISS index isn’t feasible in unit tests, keep this as an integration test behind a marker.)

---

## Operational notes

* **Resource detectors / semconv**: If you haven’t yet, keep using standard OTel semconv keys and enable process/container detectors during bootstrap; they enrich traces/logs/metrics with infra context automatically. Your prior “reconfig guide” already outlines this option. 
* **Timeline / runpack**: No code changes needed; continue emitting timeline events and packaging runpacks—these complement traces when agents want a dense “what happened” log.  

---

## Cleanups (what to remove now)

1. **Delete** `codeintel_rev/telemetry/prom.py` (legacy Prometheus endpoint + counters). Repo map shows it as both a FastAPI surface and re‑export hub. 
2. **Delete** `codeintel_rev/telemetry/otel.py` (duplicate bootstrap). Keep a single owner: `observability/otel.py`. 
3. **Sweep imports**: replace any `from codeintel_rev.telemetry.prom ...` with `from codeintel_rev.metrics.registry ...`. The test above enforces this. (You already centralize many instruments in `metrics/registry.py` per the repo map.) 
4. **Remove any `/metrics` router mount** in `app/main.py` or routers; scrape comes from OTel reader’s HTTP server. 

---

## Why this is safe and correct (repo‑grounded)

* **`telemetry/prom.py` is still present and referenced** (FastAPI surface, re‑export hub) → safe to remove and re‑point to `metrics/registry.py`. 
* **`observability/otel.py` exists** to host a single bootstrap (we extend it and remove `telemetry/otel.py`). 
* **Gating and hybrid retrieval** provide clear seams for instruments and span timing; `_gather_channel_hits` already emits per‑stage records (we don’t disturb your logic). 
* **Run‑report / runpack** code is orthogonal; no changes required. (You already accept `trace_id` in `make_runpack`.) 

---

## “Done” checklist you can run today

* [ ] `git rm codeintel_rev/telemetry/prom.py codeintel_rev/telemetry/otel.py`
* [ ] Apply all diffs above.
* [ ] `pytest -q` → `test_no_legacy_telemetry` should pass; `test_tracing_e2e` and `test_metrics_e2e` should pass locally.
* [ ] Run the server; open `http://localhost:9464/metrics` and confirm `codeintel_*` series exist (embed/FAISS latencies).
* [ ] Exercise one semantic search via MCP; confirm a single request trace and stage spans in your backend and/or the in‑memory exporter (FastAPI/MCP tool spans exist in your server modules).  

If you want me to also **sweep the codebase for your custom semantic conventions** and swap to the official OTel semconv imports in this same pass (instead of carrying a shim), I can produce a follow‑up codemod—the index shows `observability/semantic_conventions.py` is present and could be retired once all call‑sites are updated. 

---

### Appendix: Relevant evidence in your tree

* `telemetry/prom.py` in **fastapi** and **reexport‑hub** buckets (remove): 
* `observability/otel.py` and `metrics/registry.py` present (centralize here): 
* Gating / retrieval adapter seams for metrics/spans:  
* Hybrid stage accounting already exists (we leave it intact and add metrics at edges): 

---

If you’d like, I can bundle all of the above into a **single PR patch** (including the tests) or also generate a **one‑file OpenTelemetry Collector config** to forward traces/metrics downstream; you already have a working baseline config in your docs that matches this model. 
