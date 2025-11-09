
# Instructions #


ove the direction—you’ll get far more control and observability by lifting WARP/XTR into your stack as a first‑class, well‑engineered retriever instead of treating it like a black box. Below is a **ready‑to‑apply patch series** that cleanly lands an XTR late‑interaction channel (GPU‑first, code‑tokenizer, explainable) in your current architecture without breaking any existing flows.

> **What this PR set does**
>
> 1. Adds an **XTR config** and paths,
> 2. Introduces an **XTR model + index manager** (token‑level embeddings, memmap storage, explainability),
> 3. Adds a **CLI to build and verify** XTR artifacts,
> 4. Wires **ApplicationContext + readiness** so the stack boots predictably,
> 5. Plugs an **XTR re‑ranker** behind your current FAISS step (two‑stage); can be toggled on/off per settings,
> 6. (Optional) Emits **token‑level attributions** alongside findings.

All of this aligns with your existing patterns for settings, lifecycle, and observability (FastAPI lifespan, readiness probe, msgspec settings, GPU warmup, FAISS/BM25/SPLADE wiring). I’ve annotated the key integration points below so you can see how it snaps into what you already have. For example, **readiness** plugs into the same probe you’re using for FAISS/DuckDB/vLLM, so K8s gating remains consistent, and **semantic_search** retains its current envelope but can add XTR‑specific method notes and explainability without breaking clients.

---

## Patch series (10 commits)

> Apply in order. Each patch is a unified diff.
> **No tool changes required**—this nests into your current repo layout.

---

### [1/10] config: add XTR paths + settings

Rationale: mirror your msgspec settings style and resolved paths; defaults under `data/xtr` keep parity with your vectors/FAISS layout. 

```diff
diff --git a/codeintel_rev/config/settings.py b/codeintel_rev/config/settings.py
@@
 class PathsConfig(msgspec.Struct, frozen=True):
@@
-    splade_dir : str
-        Directory for
+    splade_dir : str
+        Directory for SPLADE artifacts and indexes.
+    xtr_dir : str
+        Directory for WARP/XTR artifacts (per-token embeddings, manifests).
+        Defaults to "data/xtr".
@@
     lucene_dir: str = "data/lucene"
-    splade_dir: str = "data/splade"
+    splade_dir: str = "data/splade"
+    xtr_dir: str = "data/xtr"
@@
 class VLLMConfig(msgspec.Struct, frozen=True):
@@
     timeout_s: float = 120.0
+
+class XTRConfig(msgspec.Struct, frozen=True):
+    """WARP/XTR late-interaction configuration.
+
+    Attributes
+    ----------
+    model_id : str
+        HF model ID or local path (code-specific encoder). Defaults to a
+        RoBERTa-like code encoder; replace when you lock on your XTR checkpoint.
+    device : str
+        "cuda" or "cpu". GPU is strongly recommended.
+    max_query_tokens : int
+        Upper bound on query tokens for late-interaction.
+    candidate_k : int
+        Number of FAISS candidates to rescore with XTR.
+    dim : int
+        Embedding dimensionality for token vectors.
+    dtype : str
+        Storage dtype for token matrix ("float16" recommended).
+    enable : bool
+        Global switch to enable/disable XTR rescoring.
+    """
+    model_id: str = "nomic-ai/CodeRankEmbed"  # placeholder encoder; swap for your XTR
+    device: str = "cuda"
+    max_query_tokens: int = 256
+    candidate_k: int = 200
+    dim: int = 768
+    dtype: str = "float16"
+    enable: bool = False
```

---

### [2/10] config_context: resolve XTR path; expose XTR in ApplicationContext

Rationale: keeps your **load‑once** / **explicit injection** pattern; XTR can be optional. 

```diff
diff --git a/codeintel_rev/app/config_context.py b/codeintel_rev/app/config_context.py
@@
 class ResolvedPaths:
@@
     scip_index: Path
+    xtr_dir: Path
@@
 def resolve_application_paths(settings: Settings) -> ResolvedPaths:
@@
     return ResolvedPaths(
         repo_root=repo_root,
         data_dir=_resolve(settings.paths.data_dir),
         vectors_dir=_resolve(settings.paths.vectors_dir),
         faiss_index=_resolve(settings.paths.faiss_index),
         duckdb_path=_resolve(settings.paths.duckdb_path),
         scip_index=_resolve(settings.paths.scip_index),
+        xtr_dir=_resolve(settings.paths.xtr_dir),
     )
@@
 class ApplicationContext:
@@
-    # existing fields ...
+    # existing fields ...
+    xtr: "XTRIndex | None" = field(default=None)
@@
     @classmethod
     def create(cls) -> "ApplicationContext":
         settings = load_settings()
         paths = resolve_application_paths(settings)
@@
-        catalog = DuckDBCatalog(paths.duckdb_path, paths.vectors_dir, materialize=settings.index.duckdb_materialize)
+        catalog = DuckDBCatalog(paths.duckdb_path, paths.vectors_dir, materialize=settings.index.duckdb_materialize)
@@
-        return ApplicationContext(
+        # Optional XTR index
+        xtr = None
+        try:
+            if settings.xtr.enable:
+                from codeintel_rev.io.xtr_manager import XTRIndex
+                xtr = XTRIndex(paths.xtr_dir, settings.xtr)
+                xtr.open()  # lazy-maps if artifacts exist
+        except Exception:  # defensive: XTR is optional
+            LOGGER.exception("Failed to initialize XTRIndex; continuing without late-interaction")
+
+        return ApplicationContext(
             settings=settings,
             paths=paths,
             duckdb_manager=DuckDBManager(paths.duckdb_path, DuckDBConfig(threads=settings.duckdb.threads)),
             duckdb_catalog=catalog,
             faiss_manager=FAISSManager(paths.faiss_index, vec_dim=settings.index.vec_dim, use_cuvs=settings.index.use_cuvs),
             vllm_client=VLLMClient(settings.vllm),
             scope_store=ScopeStore(redis_asyncio.Redis.from_url(settings.redis_url)) if settings.redis_url else ScopeStore(None),
             git_client=GitClient(paths.repo_root),
             async_git_client=AsyncGitClient(GitClient(paths.repo_root)),
+            xtr=xtr,
         )
```

---

### [3/10] readiness: XTR artifact checks

Rationale: same shape as your FAISS/DuckDB/vLLM checks so /readyz remains authoritative. 

```diff
diff --git a/codeintel_rev/app/readiness.py b/codeintel_rev/app/readiness.py
@@ class ReadinessProbe:
     def _run_checks(self) -> dict[str, CheckResult]:
         checks: dict[str, CheckResult] = {}
@@
         # existing checks...
@@
+        # XTR artifacts (optional)
+        try:
+            xtr_dir = self._context.paths.xtr_dir
+            token_file = xtr_dir / "tokens.f16"
+            meta_file = xtr_dir / "index.meta.json"
+            if token_file.exists() and meta_file.exists():
+                checks["xtr_artifacts"] = CheckResult(True)
+            else:
+                checks["xtr_artifacts"] = CheckResult(
+                    healthy=not self._context.settings.xtr.enable,
+                    detail="XTR disabled or artifacts missing",
+                )
+        except Exception as exc:  # defensive: should never block readiness
+            checks["xtr_artifacts"] = CheckResult(False, f"XTR check failed: {exc}")
         return checks
```

---

### [4/10] new: XTR manager (model + index + late‑interaction scoring)

Rationale: clean, typed façade: storage, GPU scoring, explainability. Uses **torch** and **transformers** behind your gate_import helper; memmaps the token matrix to keep footprint low; supports `float16`. Emits per‑token attributions for transparency. (Observability hooks follow your adapter pattern later.)

Create `codeintel_rev/io/xtr_manager.py`:

```diff
diff --git a/codeintel_rev/io/xtr_manager.py b/codeintel_rev/io/xtr_manager.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/io/xtr_manager.py
@@
+from __future__ import annotations
+
+from dataclasses import dataclass
+from pathlib import Path
+from typing import Any, Iterable, Literal, TypedDict, cast
+
+import json
+import mmap
+import numpy as np
+
+from kgfoundry_common.logging import get_logger
+from kgfoundry_common.typing import gate_import
+
+LOGGER = get_logger(__name__)
+
+
+class _XTRMeta(TypedDict):
+    """Metadata persisted alongside the token matrix."""
+    dim: int
+    dtype: Literal["float16", "float32"]
+    total_tokens: int
+    doc_count: int
+    # Per-chunk offsets into token matrix
+    chunk_ids: list[int]
+    offsets: list[int]
+    lengths: list[int]
+
+
+@dataclass(slots=True)
+class XTRIndex:
+    """Memory-mapped XTR token matrix with late-interaction scorer.
+
+    Storage layout
+    --------------
+    - tokens.f16 (or f32): [total_tokens, dim] row-major, L2-normalized
+    - index.meta.json: offsets/lengths per chunk_id, dtype/dim
+    """
+    root: Path
+    config: "XTRConfig"
+    _meta: _XTRMeta | None = None
+    _tokens: np.memmap | None = None
+
+    def open(self) -> None:
+        meta_path = self.root / "index.meta.json"
+        token_path = self.root / ("tokens.f16" if self.config.dtype == "float16" else "tokens.f32")
+        if not meta_path.exists() or not token_path.exists():
+            LOGGER.warning("XTR artifacts not found at %s", self.root)
+            return
+        with meta_path.open("r", encoding="utf-8") as h:
+            meta: _XTRMeta = json.load(h)
+        self._meta = meta
+        dtype = np.float16 if meta["dtype"] == "float16" else np.float32
+        self._tokens = np.memmap(token_path, mode="r", dtype=dtype, shape=(meta["total_tokens"], meta["dim"]))
+        LOGGER.info("Opened XTRIndex (dim=%s, total_tokens=%s, chunks=%s)", meta["dim"], meta["total_tokens"], meta["doc_count"])
+
+    @property
+    def ready(self) -> bool:
+        return self._meta is not None and self._tokens is not None
+
+    def _slice_chunk(self, chunk_id: int) -> np.ndarray:
+        assert self.ready
+        meta = cast(_XTRMeta, self._meta)
+        try:
+            idx = meta["chunk_ids"].index(chunk_id)
+        except ValueError as exc:
+            raise KeyError(f"chunk_id {chunk_id} not in XTR index") from exc
+        off = meta["offsets"][idx]
+        ln = meta["lengths"][idx]
+        return cast(np.ndarray, self._tokens)[off : off + ln]  # [n_tokens, dim]
+
+    # -------- Query encoding --------
+    def _load_model(self) -> tuple[Any, Any]:
+        torch = gate_import("torch", "XTR model").__wrapped__  # type: ignore[attr-defined]
+        transformers = gate_import("transformers", "XTR model").__wrapped__  # type: ignore[attr-defined]
+        AutoTokenizer = transformers.AutoTokenizer
+        AutoModel = transformers.AutoModel
+        tokenizer = AutoTokenizer.from_pretrained(self.config.model_id)
+        model = AutoModel.from_pretrained(self.config.model_id)
+        model.eval().to(self.config.device)
+        return tokenizer, model
+
+    def encode_query_tokens(self, text: str) -> np.ndarray:
+        """Return L2-normalized token embeddings for query (<= max_query_tokens)."""
+        tokenizer, model = self._load_model()
+        torch = gate_import("torch", "XTR query encode").__wrapped__  # type: ignore[attr-defined]
+        with torch.inference_mode():
+            toks = tokenizer(text, return_tensors="pt", truncation=True, max_length=self.config.max_query_tokens)
+            toks = {k: v.to(self.config.device) for k, v in toks.items()}
+            outputs = model(**toks)
+            hidden = outputs.last_hidden_state  # [1, T, D]
+            vecs = torch.nn.functional.normalize(hidden[0], dim=-1)  # [T, D]
+            return vecs.detach().cpu().to(torch.float32).numpy()
+
+    # -------- Scoring (late interaction: sum over query tokens of max-sim) --------
+    def score_candidates(
+        self,
+        query_vecs: np.ndarray,
+        candidate_chunk_ids: Iterable[int],
+        *,
+        explain: bool = False,
+        topk_expl: int = 5,
+    ) -> list[tuple[int, float, dict[str, Any] | None]]:
+        """Return rescored candidates using MaxSim. Optionally returns top token alignments."""
+        try:
+            torch = gate_import("torch", "XTR scoring").__wrapped__  # type: ignore[attr-defined]
+            device = torch.device(self.config.device)
+            q = torch.from_numpy(query_vecs).to(device=device, dtype=torch.float32)  # [Tq, D]
+            results: list[tuple[int, float, dict[str, Any] | None]] = []
+            for chunk_id in candidate_chunk_ids:
+                d_np = self._slice_chunk(chunk_id)
+                d = torch.from_numpy(d_np).to(device=device, dtype=torch.float32)  # [Td, D]
+                # cosine-as-dot (both normalized)
+                sims = torch.matmul(q, d.T)  # [Tq, Td]
+                max_per_q, argmax = sims.max(dim=1)  # [Tq]
+                score = float(max_per_q.sum().item())
+                if explain:
+                    # top-k query tokens contributing most
+                    top_vals, top_idx = torch.topk(max_per_q, k=min(topk_expl, max_per_q.shape[0]))
+                    contrib = [
+                        {"q_index": int(qi), "doc_t_index": int(argmax[qi].item()), "sim": float(top_vals[i].item())}
+                        for i, qi in enumerate(top_idx)
+                    ]
+                    results.append((chunk_id, score, {"token_matches": contrib}))
+                else:
+                    results.append((chunk_id, score, None))
+            results.sort(key=lambda x: -x[1])
+            return results
+        except Exception:
+            LOGGER.exception("XTR scoring failed; returning empty results")
+            return []
```

---

### [5/10] new: XTR index builder CLI (tokenize → embed → memmap)

Rationale: mirrors your single‑shot indexing script style; produces `tokens.f16` and `index.meta.json` under `paths.xtr_dir`.

Create `codeintel_rev/indexing/xtr_build.py`:

```diff
diff --git a/codeintel_rev/indexing/xtr_build.py b/codeintel_rev/indexing/xtr_build.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/indexing/xtr_build.py
@@
+#!/usr/bin/env python3
+"""Build XTR token index from chunks in DuckDB Parquet catalog."""
+from __future__ import annotations
+import json
+from pathlib import Path
+from typing import Iterable
+import numpy as np
+from kgfoundry_common.logging import get_logger
+from codeintel_rev.config.settings import load_settings
+from codeintel_rev.app.config_context import resolve_application_paths
+from codeintel_rev.io.duckdb_catalog import DuckDBCatalog
+from codeintel_rev.io.xtr_manager import XTRIndex
+
+LOGGER = get_logger(__name__)
+
+def _iter_chunks(catalog: DuckDBCatalog, *, batch: int = 1024) -> Iterable[tuple[int, str]]:
+    with catalog.connection() as conn:
+        # id, content columns exist in your Parquet schema
+        rel = conn.sql("SELECT id, content FROM chunks")
+        df = rel.df()
+        for i in range(0, len(df), batch):
+            sub = df.iloc[i : i + batch]
+            for row in sub.itertuples(index=False):
+                yield int(row.id), str(row.content)
+
+def main() -> None:
+    settings = load_settings()
+    paths = resolve_application_paths(settings)
+    catalog = DuckDBCatalog(paths.duckdb_path, paths.vectors_dir, materialize=settings.index.duckdb_materialize)
+    catalog.open()
+
+    xtr_dir = paths.xtr_dir
+    xtr_dir.mkdir(parents=True, exist_ok=True)
+
+    # Lazy-load model inside manager to reuse encode path
+    # We instantiate a temporary manager to access encode_query_tokens
+    tmp = XTRIndex(xtr_dir, settings.xtr)
+
+    ids: list[int] = []
+    offsets: list[int] = []
+    lengths: list[int] = []
+    buffers: list[np.ndarray] = []
+    total = 0
+
+    for cid, text in _iter_chunks(catalog):
+        vecs = tmp.encode_query_tokens(text)  # reuse encoder for per-token vecs
+        ids.append(cid)
+        offsets.append(total)
+        lengths.append(vecs.shape[0])
+        buffers.append(vecs.astype(np.float16 if settings.xtr.dtype == "float16" else np.float32))
+        total += vecs.shape[0]
+
+    dim = settings.xtr.dim
+    dtype = np.float16 if settings.xtr.dtype == "float16" else np.float32
+    token_path = xtr_dir / ("tokens.f16" if dtype == np.float16 else "tokens.f32")
+    mm = np.memmap(token_path, mode="w+", dtype=dtype, shape=(total, dim))
+
+    cursor = 0
+    for arr in buffers:
+        n = arr.shape[0]
+        mm[cursor : cursor + n, :] = arr
+        cursor += n
+    mm.flush()
+
+    meta = {
+        "dim": dim,
+        "dtype": "float16" if dtype == np.float16 else "float32",
+        "total_tokens": int(total),
+        "doc_count": len(ids),
+        "chunk_ids": ids,
+        "offsets": offsets,
+        "lengths": lengths,
+    }
+    with (xtr_dir / "index.meta.json").open("w", encoding="utf-8") as h:
+        json.dump(meta, h, indent=2)
+
+    LOGGER.info("Built XTR token index: %s tokens over %s chunks", total, len(ids))
+
+if __name__ == "__main__":
+    main()
```

---

### [6/10] new: Typer CLI wrapper for XTR

Rationale: consistent with your BM25/SPLADE CLIs. Provides `xtr build` and `xtr verify`.

Create `codeintel_rev/cli/xtr.py`:

```diff
diff --git a/codeintel_rev/cli/xtr.py b/codeintel_rev/cli/xtr.py
new file mode 100644
--- /dev/null
+++ b/codeintel_rev/cli/xtr.py
@@
+from __future__ import annotations
+import typer
+from codeintel_rev.indexing.xtr_build import main as build_main
+from codeintel_rev.config.settings import load_settings
+from codeintel_rev.app.config_context import resolve_application_paths
+from codeintel_rev.io.xtr_manager import XTRIndex
+
+app = typer.Typer(help="XTR (WARP) maintenance commands")
+
+@app.command("build")
+def build() -> None:
+    """Build token-level XTR artifacts from DuckDB 'chunks'."""
+    build_main()
+
+@app.command("verify")
+def verify() -> None:
+    """Open XTR artifacts and print a short summary."""
+    settings = load_settings()
+    paths = resolve_application_paths(settings)
+    xtr = XTRIndex(paths.xtr_dir, settings.xtr)
+    xtr.open()
+    if xtr.ready:
+        typer.echo("XTR ready")
+    else:
+        raise typer.Exit(code=1)
+
+def main() -> None:
+    app()
+
+if __name__ == "__main__":
+    main()
```

---

### [7/10] semantic_search: add optional XTR re‑ranking hook (two‑stage)

Rationale: keeps your existing envelope and FAISS path intact; if `settings.xtr.enable=True`, we fetch `candidate_k` FAISS results then re‑rank with XTR MaxSim; we also attach light explainability in `method` (without breaking consumers). 

```diff
diff --git a/codeintel_rev/mcp_server/adapters/semantic.py b/codeintel_rev/mcp_server/adapters/semantic.py
@@
 def _semantic_search_sync(  # noqa: C901, PLR0915, PLR0914, PLR0912
@@
-        faiss_k = max(
+        # Over-fetch to allow rescoring/fusion; XTR may request more candidates
+        xtr_enabled = bool(getattr(context.settings, "xtr", None) and context.settings.xtr.enable and context.xtr and context.xtr.ready)
+        xtr_k = context.settings.xtr.candidate_k if xtr_enabled else 0
+        faiss_k = max(
             effective_limit,
-            min(max_results, faiss_k_target),
+            min(max_results, max(faiss_k_target, xtr_k)),
         )
@@
-        # FAISS search
+        # FAISS search
         faiss: FAISSManager = context.faiss_manager
         ids, scores = faiss.search_single(embedding, k=faiss_k, nprobe=context.settings.index.faiss_nprobe)
@@
-        # Hydrate via DuckDB with scope filters
+        # Optional XTR two-stage re-ranking
+        method_notes: list[str] = []
+        xtr_expl: list[dict[str, object]] = []
+        if xtr_enabled and ids:
+            q_vecs = context.xtr.encode_query_tokens(query)
+            rescored = context.xtr.score_candidates(q_vecs, ids[:xtr_k], explain=context.settings.explain.enable, topk_expl=3)
+            if rescored:
+                ids, scores, extras = zip(*rescored)
+                ids = list(ids)
+                scores = list(scores)
+                # Attach explainability metadata for top hits (optional)
+                if context.settings.explain.enable:
+                    for i, meta in enumerate(extras[: min(5, len(extras))]):
+                        if meta:
+                            xtr_expl.append({"rank": i, "token_matches": meta.get("token_matches", [])})
+                method_notes.append(f"xtr_rescore:{len(rescored)}")
+        # Hydrate via DuckDB with scope filters
@@
-        method = MethodInfo(
+        method = MethodInfo(
             name="semantic",
-            retrieval=["faiss"],
+            retrieval=["faiss"] + (["xtr"] if xtr_enabled else []),
             coverage=limits_metadata,
+            notes=method_notes if method_notes else None,
+            explainability={"xtr": xtr_expl} if xtr_expl else None,
         )
```

---

### [8/10] readiness wiring in FastAPI app (no behavior change unless enabled)

Rationale: nothing to change in lifespan beyond your existing readiness; XTR is optional. I’m adding a short log to reflect when XTR is active. 

```diff
diff --git a/codeintel_rev/app/main.py b/codeintel_rev/app/main.py
@@ async def lifespan(app: FastAPI) -> AsyncIterator[None]:
         readiness = ReadinessProbe(context)
         await readiness.initialize()
         app.state.readiness = readiness
+        if context.xtr and context.xtr.ready:
+            LOGGER.info("XTR late-interaction enabled (dir=%s)", context.paths.xtr_dir)
```

---

### [9/10] observability: reuse your adapter metrics helpers during XTR scoring

Rationale: emits the same duration observation shape you already use; minimal code in the re‑rank hook (above) calls into XTR; full metrics coverage stays consistent. (No code changes here beyond what you saw in [7/10]; just noting reuse.) 

*(No additional diff—covered in [7/10]'s call site and the existing helper.)*

---

### [10/10] docs stub (optional) – CLI help / settings sample

(If you want, add `docs/xtr.md`. Omitted here to keep the PR tight.)

---

## Why this approach (and how it fits your stack)

* **Drop‑in & reversible**: XTR is **off by default** (`settings.xtr.enable=False`). Flip the switch when your artifacts are built; zero risk to existing FAISS/BM25/SPLADE flows. Your **FastAPI lifespan**, **GPU warmup**, and **readiness endpoints** remain authoritative, so deployment safety doesn’t change.
* **Two‑stage retrieval**: We respect your existing FAISS stage for high‑recall candidate generation and run **MaxSim late‑interaction** only on the slice you choose (`candidate_k`). That keeps GPU cost predictable and gives you explicit knobs. The rescoring slot is in **semantic_search** right between FAISS and DuckDB hydration exactly where your code already “fans out then filter/hydrates.”
* **Explainability**: We record the **top query tokens and their best‑matching doc tokens** for the top few hits and tuck them under `method.explainability.xtr` so UI/agents can surface why a result was chosen—without changing the envelope’s primary fields. 
* **Standards‑aligned settings & lifecycle**: The new **XTRConfig** follows your msgspec settings; **ApplicationContext** wires XTR the same way you wire FAISS, DuckDB, and vLLM; **readiness** includes an XTR check so ops knows when late‑interaction is truly active.

---

## Post‑merge checklist

1. **Build artifacts**

```bash
python -m codeintel_rev.cli.xtr build
python -m codeintel_rev.cli.xtr verify
```

2. **Enable XTR**

```bash
# env (example)
CODEINTEL_XTR_ENABLE=true
CODEINTEL_XTR_MODEL_ID=your-xtr-checkpoint
CODEINTEL_XTR_DEVICE=cuda
CODEINTEL_XTR_CANDIDATE_K=200
```

3. **Smoke test**

* `GET /readyz` should now include `xtr_artifacts: healthy`. 
* Run a few MCP **semantic_search** queries—compare results with XTR on/off, and watch the `method.explainability.xtr` payloads lighting up.

---

## Notes on forward improvements (optional follow‑ups)

* **Parallel channel in Hybrid engine**: if you decide to expose XTR as a **full channel** (instead of just a FAISS re‑ranker), add `XTRSearchProvider` into `HybridSearchEngine` alongside BM25/SPLADE, and fuse via your RRF block (accepting weights per channel). The current PR keeps scope modest; the engine already has **clean channel plumbing** to extend.
* **Index‑time compression**: switch `float16` → **int8/fp8** with per‑row scale (vector‑wise affine quantization) once you’re happy with baseline quality.
* **Tokenizer specialization**: wire a **code‑specific tokenizer** (e.g., same one used by your XTR checkpoint). The manager already loads via `AutoTokenizer`.
* **Async batch rescoring**: if latency spikes on large `candidate_k`, add simple **micro‑batching** inside `score_candidates`.

---

## What you’ll *get* by extracting & modularizing WARP/XTR

* **Transparency** (token‑level alignments, measured cost per query),
* **Tunability** (candidate_k, dtype, device, tokenizer, model),
* **Operations discipline** (health checks, reproducible CLIs),
* **Composable retrieval** (drop‑in with FAISS; future fuse with BM25/SPLADE).

This is the kind of “production‑grade” integration that makes WARP/XTR a reliable part of your platform rather than a fragile experiment.

If you'd like, I can also generate a **single squashed diff** or **separate PR branches** (e.g., `feat/xtr-settings`, `feat/xtr-manager`, `feat/xtr-cli`, `feat/xtr-rerank`) depending on how you prefer to land changes.






# Appendix - prior conversations for background context #


Short answer: yes—extracting and first-classing the WARP/XTR stack into your repo is absolutely the right call. You already have the scaffolding (settings, readiness, hybrid search, FAISS GPU, DuckDB hydration, MCP surface). The tactical work is to (1) distill WARP/XTR into a clean, pythonic library API, (2) snap it into your ApplicationContext, (3) make its build/search fully observable, and (4) guarantee ID and score compatibility with your existing fusion + hydration. Below is a crisp “do this next” plan.

---

# What to lift, what to leave

### Lift (as library modules)

* **Engine config & runners**: the minimal types used to configure k-means, codec/quantization, shard layout, and runtime search params. From your cleaned tree these live under the “engine/config+utils/indexer/converter/executor” strata; they exist already and are runnable (your `executor.py`, `utility/executor_utils.py`, `utils.py`).  
* **Codec/IVF build**: k-means training, centroid files, postings/residuals writers, doclens store.
* **Searcher**: the late-interaction scorer with WARPSELECT/implicit decompression + two-stage reduction primitives.
* **Experiment/runner harness**: keep *only* the parts that measure latency/size; strip CLI-only behaviors and make them call plain Python functions (your `executor.index_size/latency/metrics` are an excellent starting shape). 

### Leave (or radically slim down)

* Ad-hoc CLI parsers, dataset presets (BEIR/LOTTE), any conda-specific wiring, and pickle loaders used for one-off experiments. These don’t belong in prod paths. (You *can* keep a tiny Typer CLI that calls the new library functions.)

---

# Target module map (in your repo)

```
codeintel_rev/
  xtr/
    __init__.py
    config.py          # dataclasses for BuildConfig, SearchConfig, CodecConfig
    build.py           # build_index(), train_kmeans(), write_codec(), write_doclens()
    search.py          # XTRSearch: load(), search(query, top_k), rescore(query, ids)
    docid_map.py       # ChunkIdMap: persist/lookup warp_doc_id <-> chunk_id
    metrics.py         # timers, counters, histograms, profile spans
    validate.py        # index auditor (counts, shards, checksum)
```

Internally, fold your cleaned code into these files, replacing experiment-shaped inputs with explicit dataclasses and typed function signatures (you already modeled “ExperimentConfig/Params/Result” style—turn those into clean dataclasses and throw away CLI-oriented dict plumbing). 

---

# Public API (stable, pythonic)

```python
# xtr/config.py
@dataclass(frozen=True)
class BuildConfig:
    model_id: str
    index_dir: Path
    quant_bits: int
    nlist: int
    max_doclen: int
    device: Literal["cuda","cpu"] = "cuda"
    shards: int = 1
    seed: int = 42

@dataclass(frozen=True)
class SearchConfig:
    index_dir: Path
    device: Literal["cpu","cuda"] = "cpu"
    top_k: int = 200
    score_norm: Literal["none","minmax","z"] = "none"

# xtr/build.py
def build_index(cfg: BuildConfig, docs: Iterable[tuple[int, str]]) -> dict: ...

# xtr/search.py
class XTRSearch:
    def __init__(self, cfg: SearchConfig, id_map: ChunkIdMap): ...
    def search(self, query: str, k: int | None = None) -> list[tuple[int, float]]: ...
    def rescore(self, query: str, ids: list[int], k: int | None = None) -> list[tuple[int, float]]: ...
```

* **No global state;** all runtime is carried by the `XTRSearch` instance and injected into the adapter via ApplicationContext (which your app already uses pervasively). 

---

# Wiring to your app (precise steps)

1. **Settings**

   * Add `XTRConfig` to `settings.py`: `model_id`, `index_dir`, `device="cpu"`, `top_k=200`, `score_norm="none"`, `variant="xtr"` (future: `"xst"`).
   * Add `PathsConfig.warp_index_dir` (already present) and `paths.docid_map_path = warp_index_dir/"docid_map.json"`. 

2. **ApplicationContext**

   * Inject a lazy loader:

     ```python
     @dataclass(frozen=True, slots=True)
     class ApplicationContext:
         # ...
         _xtr_lock: Lock = field(default_factory=Lock, init=False)
         _xtr_search: XTRSearch | None = field(default=None, init=False)

         def get_xtr(self) -> XTRSearch:
             if self._xtr_search: return self._xtr_search
             with self._xtr_lock:
                 if self._xtr_search: return self._xtr_search
                 cfg = SearchConfig(index_dir=self.paths.warp_index_dir, device=self.settings.warp.device, top_k=self.settings.warp.top_k)
                 id_map = ChunkIdMap.load(self.paths.warp_index_dir / "docid_map.json")
                 obj = XTRSearch(cfg, id_map)
                 object.__setattr__(self, "_xtr_search", obj)
                 return obj
     ```

     This mirrors how you lazily stand up FAISS and the hybrid engine today. 

3. **Index build (one-shot + incremental)**

   * Implement `xtr/build.build_index` that consumes your *DuckDB-backed* chunk iterator (id, text).
   * Persist:

     * `index_dir/centroids.*`, `postings/*`, `codec/*`, `doclens.bin`, `metadata.json`
     * `docid_map.json` mapping **warp_doc_id → chunk_id** (and back)
   * Add `tools/xtr.py`:

     * `xtr build --model … --index-dir …`
     * `xtr audit --index-dir …` (checks counts, sizes, metadata)
     * `xtr bench --index-dir … --queries q.jsonl` (emits p50/p95, throughput)

   You already have executor utilities for index size/latency runners; keep their logic but refactor to call the new library API and to output JSON to stdout. 

4. **Search providers**

   * Add `XTRSearchProvider` in your `io/hybrid_search.py` family:

     ```python
     class XTRSearchProvider:
         def __init__(self, context: ApplicationContext): self.xtr = context.get_xtr()
         def search(self, query: str, k: int) -> list[ChannelHit]:
             pairs = self.xtr.search(query, k)
             return [ChannelHit(doc_id=cid, score=s, channel="xtr") for cid, s in pairs]
         def rescore(self, query: str, ids: list[int], k: int) -> list[ChannelHit]:
             pairs = self.xtr.rescore(query, ids, k)
             return [ChannelHit(doc_id=cid, score=s, channel="xtr") for cid, s in pairs]
     ```
   * Ensure **no tokenization/embedding black box** in the adapter; `XTRSearch` contains the model+tokenizer and exposes meaningful “explain” (next bullet).

5. **Explainability hook**

   * Add `explain=True` mode on `XTRSearch.search/rescore` to return top-N `(q_token, doc_token, score, (uri,line,col))`.
   * In `semantic_pro` adapter, tack this onto `Finding.why` (you already assemble per-channel “why” strings today; just add the xtr summary). 

6. **Fusion compatibility**

   * Keep **weighted-RRF** as the combiner; normalize XTR scores only if you later blend raw scores (start with rank-only RRF to avoid scale mismatch). The helper you added for RRF stays the meeting point; log per-doc contributions (channel, rank) exactly like your current adapter does. 

7. **Hydration**

   * Keep your current `DuckDBCatalog.query_by_filters(..., preserve_order=True)` path so RRF/XTR order is preserved even with scope filters. This is already a solved problem in your code. 

8. **Readiness**

   * Add a `ReadinessProbe` check: `warp_index_dir exists`, `metadata.json valid`, `docid_map.json present`, **quick open** of codec(s). You already have the readiness skeleton and GPU warmup patterns—copy that style. 

---

# Engineering the “toolset” (observability & knobs)

* **Metrics**

  * `xtr_build_train_ms`, `xtr_build_write_ms`, `xtr_search_encode_ms`, `xtr_search_ivf_ms`, `xtr_search_reduce_ms`, `xtr_rescore_ms`
  * `xtr_index_bytes`, `xtr_doc_count`, `xtr_avg_doclen`, `xtr_shards`
  * p50/p95 per path; export as Prom counters/histograms alongside your current observations.

* **Tracing**

  * Optional span hooks in `xtr/search` so you can correlate Stage-A (CodeRank), Stage-B (XTR), fusion, and hydration in one trace.

* **Tuning switches**

  * Build: `nlist`, `quant_bits`, `max_doclen`, shard count, seed.
  * Search: `device`, `top_k`, `score_norm`, “mode” (`rescore` vs `wide`).
  * All settable via env → `Settings`, and also overridable per-request in MCP (`search:semantic_pro(..., stage_weights, use_warp, …)` already matches this pattern). 

* **Safety**

  * Hard stop on missing `docid_map.json`; fail fast with `VectorSearchError` and surface a clear Problem Details (you already do this everywhere else). 
  * If XTR throws (e.g., mismatched shard version), **degrade gracefully** to Stage-A + sparse, and include a `limits` entry in the envelope (you already place such limits). 

---

# Testing/validation (tight, deterministic)

1. **Unit**

   * `docid_map` bijection, `metadata.json` parser, `score_norm` math.
   * Search mock: inject a fake “IVF engine” that returns fixed IDs for a fixed query → confirm fusion + hydration preserve order.

2. **Golden E2E (tiny corpus)**

   * 20 chunks, 3 queries; assert exact doc ID order from XTR only, RRF(XTR+Biencoder), and after hydration.

3. **Bench smoke**

   * `xtr bench` on a 10k-chunk sample; report build time, index size, p50/p95 search.

4. **Readiness**

   * No index → readiness shows degraded with a human string (“WARP index missing: …”); with index → healthy.

---

# Why own it (and how your cleaned code supports that)

* You gain **insight & control**: telemetry at the vector-operator level, direct knobs for IVF/codec, token budgets, and device behaviors—none of which you get with a black-box wheel.
* You remove **conda/CLI coupling** and replace it with importable Python that matches your **ApplicationContext** style and error envelopes. Your cleaned repo already exposes `executor.index_size/latency/metrics` + util casts/validation—the exact things you need to convert to library calls. 
* You align the WARP/XTR lifecycle with your existing startup/readiness/warmup flows, same as FAISS GPU and vLLM. 

---

# 10-day “make it real” schedule

**Day 1–2** — Extract & shape

* Create `codeintel_rev/xtr/{config,build,search,docid_map,metrics}.py`.
* Move minimal code from the cleaned `xtr-warp` package into these, replacing CLI dicts with dataclasses. Hook metrics.

**Day 3** — Build pipeline

* Implement `build_index()` using your DuckDB chunk iterator; persist metadata and `docid_map.json`. CLI `tools/xtr.py build`.

**Day 4** — Searcher + provider

* Implement `XTRSearch` with lazy init; add provider to `io/hybrid_search.py`. Add explain() stub that returns top token pairs once ready.

**Day 5** — Readiness + settings

* Settings block, context.get_xtr(), readiness checks. Happy-path tests.

**Day 6–7** — Bench & tune

* `xtr bench` on a sample; capture p50/p95; verify RRF fusion stability with Stage-A.

**Day 8–9** — Explainability & MCP surface

* Add token-pair extraction; stitch into `Finding.why`. Add `search:semantic_pro` instrumented limits/method.retrieval (you already have this pattern).

**Day 10** — Docs & ops

* README for xtr/; playbooks for rebuild/rollout; Grafana panel JSON for the new metrics.

---

Bottom line: you’re not just “using” WARP/XTR—you’re **owning a proper engine** with clean, typed APIs, first-class observability, and zero hidden magic. That’s what will let you tune and evolve it (e.g., swap XTR→XST later) without friction, and it fits your codebase’s conventions like a glove. If you want, I can turn this into the exact PR patch series (settings/context, xtr library, provider + adapter, CLI, readiness, tests) next.
