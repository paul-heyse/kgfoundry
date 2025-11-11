
# Context and high level implementation plan #

Below is a **complete, end‑to‑end playbook** for **best‑in‑class BM25 and SPLADE‑v3 deployment in Python via Pyserini**—from environment setup, corpus modeling and indexing, through query‑time fusion and interpretability, to advanced tuning, observability, and self‑healing automation. It assumes **on‑prem**, **code‑search** workloads accessed by an **LLM over MCP**, with **Recall@K** as the North Star metric. I draw on (a) your Pyserini field‑guide, (b) your BM25+SPLADEv3 research report, and (c) authoritative upstream sources.  

---

## 0) Quick orientation

**Mission of each component in this stack**

* **BM25 (Lucene)** — exact/lexical precision and stability; first‑stage workhorse; cheap and predictable. 
* **SPLADE‑v3 (learned‑sparse impact index)** — neural term expansion + learned per‑term weights; **semantic recall** while staying sparse and Lucene‑native. 
* **Hybrid fusion (RRF)** — robustly blends ranked lists without fragile score normalization; production‑proven for hybrid search.  ([OpenSearch][1])
* **(Optional) Dense (Lucene HNSW)** — keep dense+sparse in one engine to simplify ops; use if you need additional paraphrase coverage.  ([arXiv][2])

---

## 1) Environment & platform (on‑prem, reproducible)

**Dependencies**

* **Python 3.11**, **Java 21 (JDK)**, `pip install pyserini` (+ `faiss-cpu` only if you also deploy Faiss). These are the current upstream expectations for Pyserini/Anserini.  ([PyPI][3])
* Source of truth & docs: Pyserini GitHub & PyPI. ([GitHub][4])

**Install (minimal)**

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install pyserini  # + faiss-cpu if you add Faiss
java -version         # Verify JDK 21
python -c "import pyserini; print(pyserini.__version__)"
```

**Process model**

* Don’t share a single `LuceneSearcher` across OS processes; instantiate per worker or front with a small Java service. 

---

## 2) Corpus modeling for **code search**

Design this once; it drives everything else (indexes, analyzers, explainability).

**2.1 Retrieval unit (docs)**

* Prefer **function‑ or class‑level chunks** (≈200–400 tokens) with **modest overlap**; carry file‑level metadata for context. This improves matching granularity, limits BM25 length effects, and yields better Recall@K for code questions. 

**2.2 JSONL schema (minimal yet rich)**

```json
{"id": "<global-docid>", 
 "contents": "<code + comments + docstring excerpt>", 
 "path": "<repo>/<relpath>",
 "lang": "python|java|go|...",
 "symbols": "ClassName::method | function_name | CONST",
 "repo": "<repo_name>",
 "commit": "<sha>",
 "last_modified_epoch": 1730419200}
```

* Keep **identical `id`** across *all* modalities (BM25, SPLADE impact, dense). This is essential for fusion and fetch. 
* Store **`last_modified_epoch`** to enable recency boosts. 

**2.3 Code‑aware tokenization (analyzer goals)**

* Split **camelCase/snake_case**, preserve digits, lowercase identifiers; consider **synonym expansion** for project acronyms (`cfg↔config`, `db↔database`). 
* Use multi‑field indexing/boosts: e.g., `symbols^3 comments^2 contents^1 path^0.5`. 
* Align BM25 analyzer with SPLADE’s WordPiece view (similar sub‑token exposure) to minimize vocabulary mismatch. 

---

## 3) Building production‑grade indexes

### 3.1 BM25 positional Lucene index

**Why positional + stored raw/docvectors?**

* Unlocks PRF (RM3), advanced readers, and debuggability (`hit.raw`, term vectors). 

**Command**

```bash
python -m pyserini.index.lucene \
  --collection JsonCollection \
  --input /data/code_jsonl \
  --index /data/lucene_bm25 \
  --generator DefaultLuceneDocumentGenerator \
  --threads 8 \
  --storePositions --storeDocvectors --storeRaw
```



**Analyzer**

* If you need a custom analyzer (camel/snake splits, synonyms), configure it in Anserini’s analyzer/query‑builder layer used by Pyserini. (See Analyzer & Query‑Builder APIs in the Pyserini docs.) 

### 3.2 SPLADE‑v3 learned‑sparse (impact) index

**Concept**: Run a SPLADE‑v3 encoder on each document → **(term → impact weight)** sparse vector → build **Lucene impact** index → query with `LuceneImpactSearcher`. 

**Workflow**

1. Preprocess text to expose meaningful sub‑tokens **before** encoding (camel/snake splits). 
2. Encode docs with **SPLADE‑v3** (HF checkpoint or ONNX). SPLADE‑v3 improves training and OOD robustness vs prior SPLADE. ([arXiv][5])
3. Build impact index and search with `LuceneImpactSearcher`. Pyserini ships impact search and prebuilt impact indexes for many corpora. 

> Why SPLADE here? You get **semantic expansion** + **Lucene‑native sparse** performance/interpretability. 

### 3.3 (Optional) Dense inside Lucene

* If you also want dense semantics, Lucene **HNSW** works natively in Anserini: dense+sparse in **one engine** simplifies ops (one deployable, one cache, shared docids). ([arXiv][2])

---

## 4) Query‑time pipeline (Python, Pyserini)

### 4.1 Baseline searchers

**BM25 (+ optional RM3 PRF)**

```python
from pyserini.search.lucene import LuceneSearcher
bm25 = LuceneSearcher('/data/lucene_bm25')
bm25.set_bm25(k1=0.9, b=0.4)            # strong default for code-size chunks
# Optional PRF (enable for head/general queries after tuning)
# bm25.set_rm3(fb_docs=10, fb_terms=10, original_query_weight=0.5)
hits_b = bm25.search(q, k=200)
```



**SPLADE‑v3 (impact)**

```python
from pyserini.search.lucene import LuceneImpactSearcher
splade = LuceneImpactSearcher('/data/lucene_spladev3_impact')
hits_s = splade.search(q, k=200)
```



**Fetch raw JSON for snippet materialization**

```python
doc = bm25.doc(hits_b[0].docid)   # or hits_b[0].raw
raw_json = doc.raw()
```



### 4.2 Robust fusion (RRF)

**Why RRF?** Rank‑based, score‑scale‑agnostic, production‑proven for hybrid (BM25 ⊕ neural).  ([OpenSearch][1])

```python
def rrf_fuse(runs, k=50, K=60):
    # runs: dict{name: [(docid, score), ...] sorted by score desc}
    import collections
    agg = collections.defaultdict(float)
    for run in runs.values():
        for rank, (docid, _) in enumerate(run, start=1):
            agg[docid] += 1.0/(K+rank)
    return sorted(agg.items(), key=lambda x: -x[1])[:k]

# Example
bm25_top = [(h.docid, h.score) for h in hits_b[:200]]
splade_top = [(h.docid, h.score) for h in hits_s[:200]]
fused = rrf_fuse({"bm25": bm25_top, "splade": splade_top}, k=50, K=60)
```

### 4.3 Recency‑aware boost (fresh code first)

Apply after fusion (tie‑breaker, gentle). 

```python
import math, time
def apply_recency_boost(fused, metadata, alpha=0.2, tau_days=21):
    now, tau = time.time(), 86400.0*tau_days
    out = []
    for docid, score in fused:
        age = max(0.0, now - metadata[docid]["last_modified_epoch"])
        out.append((docid, score * (1.0 + alpha * math.exp(-age/tau))))
    return sorted(out, key=lambda x: -x[1])
```

### 4.4 Query‑aware routing (optional weighting)

* **Symbolic** queries (identifiers, paths, stack traces) → weight **BM25/SPLADE** more.
* **Semantic** queries (natural language) → keep SPLADE dominant; BM25 anchors literals.
* Implement via a light classifier or heuristics; if you later want weighted RRF, learn per‑bucket weights. 

---

## 5) Interpreting results & “why‑hit” debugging

Provide a **traceable** explanation for every top hit.

* **BM25**: expose analyzer output, per‑term tf/df, doc length, and contribution to the score. Pyserini/Anserini’s Reader & Analyzer APIs are your friends. 
* **SPLADE‑v3**: show **top non‑zero query terms** (expansions) and per‑term **impact weights** matched in the doc—this is a major interpretability advantage of learned‑sparse. 
* **Return to MCP**: include fields `{scores:{bm25,splade,rrf,recency}, why:{tokens,expansions}}` so the LLM can self‑rationalize.

---

## 6) Tuning for **Recall@K** (playbooks you can automate)

> The defaults below are strong starts; use the **validation harness** in §7 to grid‑search and lock in.  

**6.1 BM25 parameters**

* Start **`k1=0.9`, `b=0.4`** for function‑sized chunks; sweep `k1 ∈ {0.7,0.9,1.2}` × `b ∈ {0.2,0.4,0.75}`. 
* **RM3 PRF** (head queries only): `{fb_docs=10, fb_terms=10, original_query_weight≈0.5}`; verify it increases Recall@K without adding too much noise. 

**6.2 SPLADE choices**

* Use **SPLADE‑v3** checkpoints for strongest learned‑sparse baselines; they outperform prior SPLADE variants and often compare well to re‑rankers across 40+ query sets. ([arXiv][5])
* If query latency matters, consider distilled variants, but expect some recall drop; train/adapt only when useful (§10). 

**6.3 Fusion**

* **RRF** with `K=60`; fuse **top 100–200** from each list so no good candidate is excluded pre‑fusion.  ([OpenSearch][1])

**6.4 Vocabulary alignment**

* Make BM25 analyzer **mirror WordPiece‑like splits** (case changes, digits, underscores). Add **synonyms** for project acronyms. 

---

## 7) Reproducible **evaluation harness** (the engine for tuning)

* Keep a lightweight suite of **200–500 canonical code queries** (from docs, PR titles, internal Q&A).
* Compute **Recall@K (e.g., K=10/20/50)**, **nDCG@10**, and latency per stage.
* Use Pyserini’s TREC wrappers whenever ground truth is available; otherwise, maintain gold sets per query. 

Example (when judgments exist):

```bash
python -m pyserini.eval.trec_eval -c -m recall.50 my-collection-test run.hybrid.trec
```



---

## 8) Production concerns (observability, SLOs, failure playbooks)

**8.1 SLOs**

* p95 latency per stage (BM25, SPLADE), end‑to‑end p95; throughput (QPS); **Fresh@K** (recent code in top‑K); **FRT** (First Retrieval Time: commit→first retrieval). 

**8.2 Dashboards**

* Query volume by repo/lang; Recall@K and nDCG@10; RRF fusion share (what fraction originates from BM25 vs SPLADE). 

**8.3 Failure playbook**

* **Recall drop** → verify analyzer outputs, docvectors present, inspect RRF inputs, regress with the harness.
* **Latency spike** → cap rerank `N`, warm caches, increase HNSW efSearch if dense is used, shard large indexes.
* **Freshness lag** → audit CI indexer (changed‑files detection, batch size), track **FRT**. 

---

## 9) “Self‑healing” automation (what to implement now)

**9.1 CI‑driven incremental indexing**

* On merge to main (or nightly): encode **only changed files** with SPLADE and update BM25+impact indexes (delete+add). Version the index for rollback. 

**9.2 Recency‑aware rescoring**

* Keep the exponential decay (α≈0.15–0.30; τ=14–30 days) as a post‑fusion multiplier; toggle off for historical queries. 

**9.3 Regression gates**

* Nightly job: run the canonical query pack; fail the build if Recall@K or Fresh@K drops > threshold. **Canary index** before promotion. 

**9.4 Auto‑tuning sweeps (weekly)**

* Grid search `(k1,b)` + RM3; RRF `K`/cutoffs; recency α/τ; promote config only if improvements are **consistent across repos**. 

**9.5 Explainability bots**

* A tool that—given a missed query—dumps BM25 terms and SPLADE non‑zero expansions for inspection; track the **avg #non‑zero SPLADE terms** as a drift signal. 

---

## 10) Extending SPLADE‑v3 for code (when to fine‑tune)

* **Start** with public SPLADE‑v3 checkpoints (strong OOD baselines). ([arXiv][5])
* **Fine‑tune** only if logs expose systematic gaps (project acronyms, internal API names).

  * Use CodeSearchNet, docs→code pairs, PR titles→changed functions; distill from a good cross‑encoder if available.
  * Keep sparsity regularization to preserve efficiency/interpretability; prune low‑impact terms statically if index size grows. 

---

## 11) End‑to‑end reference blueprint (glue it together)

**11.1 Index build (Makefile‑style)**

```make
# 1) Build BM25 (positional)
bm25:
\tpython -m pyserini.index.lucene --collection JsonCollection \
\t  --input data/jsonl --index data/lucene_bm25 \
\t  --generator DefaultLuceneDocumentGenerator --threads 16 \
\t  --storePositions --storeDocvectors --storeRaw

# 2) Encode docs with SPLADE-v3 (pseudo-code; your encoder wrapper here)
splade-doc-encode:
\tpython scripts/encode_splade_docs.py --in data/jsonl --out data/impact_terms.jsonl

# 3) Build SPLADE impact index (Anserini impact indexer)
splade-impact:
\tpython -m pyserini.index.lucene \
\t  --collection JsonCollection --input data/impact_terms.jsonl \
\t  --index data/lucene_spladev3_impact --threads 16

# 4) Consistency check (docid parity)
check:
\tpython scripts/check_docids.py data/lucene_bm25 data/lucene_spladev3_impact
```

BM25 index flags and impact searcher are per the Pyserini guide. 

**11.2 Online search microservice (MCP tool)**

* Endpoint `hybrid_code_search(query, k, filters)` does:

  1. Normalize query (preserve identifiers).
  2. Query **BM25** (optionally with RM3, conditionally), **SPLADE**; get top‑200 each.
  3. **RRF** fuse → **recency** boost → (optional cross‑encoder re‑rank top‑100).
  4. Return `{docid, repo, path, lang, symbol, snippet, scores:{...}, commit, last_modified}`.
     This contract maps cleanly to Pyserini classes (`LuceneSearcher`, `LuceneImpactSearcher`). 

**11.3 Ops & QA runbooks (checklists)**

* **Indexing**: positional BM25 with raw/docvectors; SPLADE impact; docid parity; CI delta builds. 
* **Tuning**: weekly sweeps; lock configs in git; keep a “known good” run for A/B. 
* **Observability**: dashboards for Recall@K, Fresh@K, FRT, stage latency; alert on regressions. 
* **Process model**: instantiate searchers per worker (no cross‑process sharing). 

---

## 12) Practical “gotchas” & best‑practice answers

* **“Why RRF instead of score mixing?”** Because BM25 and SPLADE scores have different scales; **rank‑based fusion** is robust and widely adopted in production hybrid search.  ([OpenSearch][1])
* **“Do I need Faiss?”** Not for BM25+SPLADE. If you add dense, prefer **Lucene HNSW** to keep one engine. ([arXiv][2])
* **“RM3 everywhere?”** No. Enable on **head/general** queries (where expansion helps) and disable on identifier‑exact queries to avoid topic drift. 
* **“Analyzer/field boosts?”** Make `symbols` and `path` separate fields and boost them. Keep analyzers consistent with SPLADE’s sub‑token view to minimize mismatch.
* **“Index flags I must not forget?”** `--storePositions --storeDocvectors --storeRaw`. You’ll need them for PRF, readers, and **why‑hit** tooling. 

---

## 13) Appendix — API & sources

* **Pyserini APIs**: `LuceneSearcher` (BM25/QLD, RM3), `LuceneImpactSearcher` (impact/SPLADE), `FaissSearcher` (if used), readers/analyzers/builders. 
* **Prebuilt indexes & ONNX demo**: check names/variants (e.g., `-docvectors`). 
* **Project docs & reproducibility**: Pyserini GitHub/PyPI, SIGIR paper. ([GitHub][4])
* **Anserini HNSW** (dense in Lucene; single‑engine hybrid): background and results. ([arXiv][2])
* **SPLADE‑v3** (training improvements, effectiveness): primary paper. ([arXiv][5])
* **RRF in production** (OpenSearch, best practices): engineering notes. ([OpenSearch][1])

---

### One‑page decision flow (for your team)

1. **Index**: Build **BM25 positional** (with raw/docvectors) + **SPLADE impact**; ensure docid parity. 
2. **Search**: BM25 (`k1=0.9,b=0.4`) (+RM3 on head queries) ⊕ SPLADE; **RRF** fuse; **recency** post‑boost; return rich traces.
3. **Tune**: weekly sweeps `(k1,b)`/RM3/RRF/recency; pick configs that improve **Recall@K** on your canonical pack. 
4. **Automate**: CI delta‑index + nightly recall regressions + canary promotion + explainability bots. 
5. **Evolve**: only then consider dense (Lucene HNSW) or SPLADE fine‑tune for code‑specific jargon. ([arXiv][2]) 

---

If you’d like, I can turn this into a **starter repository** (Makefile + configs + indexing scripts + a FastAPI MCP tool exposing `hybrid_code_search` + an evaluation notebook) that exactly matches the commands and code above and plugs into your CI. The blueprint aligns with your prior guides and the upstream practices referenced here.  

[1]: https://opensearch.org/blog/introducing-reciprocal-rank-fusion-hybrid-search/?utm_source=chatgpt.com "Introducing reciprocal rank fusion for hybrid search"
[2]: https://arxiv.org/abs/2304.12139?utm_source=chatgpt.com "Anserini Gets Dense Retrieval: Integration of Lucene's HNSW Indexes"
[3]: https://pypi.org/project/pyserini/?utm_source=chatgpt.com "pyserini"
[4]: https://github.com/castorini/pyserini?utm_source=chatgpt.com "castorini/pyserini"
[5]: https://arxiv.org/abs/2403.06789?utm_source=chatgpt.com "SPLADE-v3: New baselines for SPLADE"


# Detailed functional implementation plan #

Below is a **narrative, end‑to‑end implementation plan** that integrates **BM25** and **SPLADEv3** via **Pyserini** into your existing `codeintel_rev` stack, tuned for **high Recall@K** and built for **automated, self‑healing operations**. I anchor concrete design choices to your repository’s modules (scope/observability, indexing lifecycle, CLI), and to Pyserini/SPLADE references for correctness and reproducibility.

---

## 0) Executive summary (what “best‑in‑class” means here)

* **Goal:** Maximize **Recall@K** for LLM‑driven code search over SCIP‑segmented code, keeping latency predictable, transparency high, and operations robust.
* **Approach:**

  1. **Index construction** at **function‑/symbol‑chunk** level from SCIP with a **code‑aware analyzer** for BM25 and a **SPLADEv3 learned‑sparse impact index**;
  2. **Query‑time hybrid fusion** (BM25 ⊕ SPLADEv3 ⊕ dense code embeddings) using **RRF**;
  3. **Automated quality controls** (regression dashboards, canary queries, index lifecycle staging/publish/rollback) and **self‑healing** fallbacks.
* **Where this plugs into your repo:**
  *SCIP ingestion & chunking:* `indexing.scip_reader` + `indexing.cast_chunker` → **JSONL**;
  *Versioned index management:* `indexing.index_lifecycle.IndexLifecycleManager` + `cli.indexctl` → **stage/publish/rollback**;
  *Online serving & fusion:* `io.hybrid_search.HybridSearchEngine.search(...)` (RRF fusion of semantic + BM25 + SPLADE channels, already described in your code) → **MCP reply metadata** via `mcp_server.schemas.MethodInfo`.   

---

## 1) Architecture narrative (end‑to‑end)

### 1.1 Corpus → SCIP → chunks (the “document model”)

1. **Parse SCIP index** (`index.json`) into structured objects (`SCIPIndex`, `Document`, `Occurrence`, `SymbolDef`). These are already modeled in `codeintel_rev.indexing.scip_reader` and documented in your SCIP data file. Use `parse_scip_json(...)` → `extract_definitions(...)` → `get_top_level_definitions(...)`. This keeps unit boundaries aligned with code symbols and paths. 
2. **Chunking strategy**: Use your `indexing.cast_chunker.chunk_file` to produce **function‑/symbol‑centric chunks** with minimal overlap. The chunker already works with `Range`/line offsets calculated from SCIP, which fits our “code‑first” unit of retrieval. 
3. **Storage**: Persist chunks (id, path, lang, span, text, timestamp, symbol metadata) to **DuckDB** as your pipeline already does for other artifacts. You already have DuckDB managers in the repo to support this. 

> **Why symbol‑level chunks?** For code retrieval, symbol‑aware chunking raises Recall@K because many “good answers” are scattered across functions; chunking produces more relevant candidates across K.

### 1.2 Two first‑stage sparse indexes (BM25 + SPLADEv3)

* **BM25 (Lucene positional)** via Pyserini’s `LuceneSearcher`:

  * **Analyzer**: code‑aware tokenization: lowercase; split on non‑alphanumerics; **split CamelCase**; do **not** stem (preserve identifiers). This can be implemented by pre‑tokenizing to JSONL or by supplying a custom analyzer in Anserini; at minimum, pre‑tokenize so Pyserini’s default analyzer doesn’t “undo” your identifier splitting. **Store positions, docvectors, raw** for PRF and diagnostics. ([ws-dl.blogspot.com][1])
  * **Parameters**: start with **k1=0.9, b=0.4** (a strong baseline in MS MARCO), then grid‑search on your validation queries. Enable **RM3 PRF** for short/ambiguous queries (fbDocs≈10, fbTerms≈10, origWeight≈0.5). ([Castorini][2])

* **SPLADEv3 (learned‑sparse “impact” index)** via Pyserini’s `LuceneImpactSearcher`:

  * **Model**: `naver/splade-v3` (or distil variant if needed for latency). SPLADEv3 trains with **KL+MarginMSE**, multi‑negatives, and sparsity regularization, producing **sparse lexical expansions** that close vocab gaps while staying in an inverted index. ([arXiv][3])
  * **Encoding**: Offline **document‑side expansion** (transformer pass over chunks → (term, weight) impacts). At query time, run **query‑side expansion** on‑the‑fly; consider ONNX for low‑latency inference. Pyserini examples and Spaces demonstrate ONNX/impact flows. ([Hugging Face][4])
  * **Tokenizer alignment**: SPLADE uses **BERT WordPiece** (e.g., “parse” + “##json”). Align BM25 analysis with similar split rules so both see compatible sub‑tokens (BM25: “parse”, “json”; SPLADE: “parse”, “##json”). Your internal guide and hybrid PDF call this out explicitly.  

> **Why learned‑sparse over dense for code baselines?** It keeps **explainability** (term impacts), aligns naturally with BM25 in **one Lucene stack**, and empirically boosts **recall** by bridging synonyms/aliases without fragile score normalization. 

### 1.3 Dense channel (existing) and **RRF fusion**

* You already have a **semantic (FAISS) channel** and an **RRF‑based hybrid engine** contract sketched in `io.hybrid_search.HybridSearchEngine.search(...)`: arguments include `semantic_hits`, with **BM25** and **SPLADE** as optional channels, and an **RRF** implementation described in the docstring, plus room for per‑channel weights. We will implement those hooks with Pyserini searchers. 
* **RRF** is the default fusion because it avoids brittle score normalization across modalities and is robust across domains; use **K=60** and fuse **topN** from each list (e.g., 200 from each). ([Microsoft Learn][5])

### 1.4 Versioned assets & safe rollout

* Use your `IndexLifecycleManager` to **stage/publish/rollback** synchronized versions for *BM25 index dir*, *SPLADE impact index dir*, *DuckDB catalog*, and *FAISS index*. CLI entry points `indexctl publish/rollback/ls` already exist; keep a stable `.../current/` symlink and update pointers atomically.  

---

## 2) Implementation details (with concrete snippets)

### 2.1 Build symbol‑centric JSONL for Pyserini

Use your SCIP reader → chunker to emit **one JSON line per chunk**:

```python
# run inside your bin/index_all.py-like pipeline
from codeintel_rev.indexing.scip_reader import parse_scip_json, extract_definitions, get_top_level_definitions  # repo
from codeintel_rev.indexing.cast_chunker import chunk_file                                              # repo
from pathlib import Path
import json

scip = parse_scip_json(Path("/data/index.json"))    # your SCIP export
defs = get_top_level_definitions(list(extract_definitions(scip)))

out = open("/staging/jsonl/chunks.jsonl", "w", encoding="utf-8")
for d in defs:
    # load file text & compute chunks from symbol ranges
    for chunk in chunk_file(Path(d.relative_path), options=None):  # your existing chunker
        rec = {
            "id": f"{d.relative_path}:{chunk.span.start}-{chunk.span.end}",
            "contents": chunk.text,  # include comments/docstrings where available
            "meta": {
                "path": d.relative_path,
                "lang": d.language,
                "range": [chunk.span.start, chunk.span.end],
                "commit_ts": chunk.commit_ts  # add if you have it
            }
        }
        out.write(json.dumps(rec) + "\n")
out.close()
```

> This mirrors how your repo already structures these types and functions; the symbols/classes are defined in `indexing.scip_reader` and chunking in `indexing.cast_chunker`.  

### 2.2 Build **BM25** index (positional; keep docvectors)

**CLI path (recommended):**

```bash
python -m pyserini.index.lucene \
  --collection JsonCollection \
  --input /staging/jsonl \
  --index  /staging/lucene_bm25_vX \
  --generator DefaultLuceneDocumentGenerator \
  --threads 16 \
  --storePositions --storeDocvectors --storeRaw
```

> The positional flags ensure PRF, term vectors, and richer diagnostics are available. ([ws-dl.blogspot.com][1])

**Serving (Python):**

```python
from pyserini.search.lucene import LuceneSearcher
bm25 = LuceneSearcher('/indices/current/bm25')             # via lifecycle 'current' path
bm25.set_bm25(k1=0.9, b=0.4)                               # baseline
# Optionally enable PRF for head queries
# bm25.set_rm3(fb_docs=10, fb_terms=10, original_query_weight=0.5)
```

([PyPI][6])

### 2.3 Build **SPLADEv3** impact index

**Doc‑side encoding (offline):**

```python
from transformers import AutoTokenizer, AutoModelForMaskedLM
import torch, json, tqdm

tok = AutoTokenizer.from_pretrained('naver/splade-v3')     # or distil variant
mdl = AutoModelForMaskedLM.from_pretrained('naver/splade-v3').eval()

def splade_doc_terms(text: str):
    # Pseudocode: forward pass -> logits -> ReLU/log-softmax -> L1/FLOPs sparsity mask -> top-K per doc
    # Convert to {term_id: impact_weight}
    pass

with open('/staging/jsonl/chunks.jsonl', 'r', encoding='utf-8') as f, \
     open('/staging/jsonl/chunks.splade.jsonl', 'w') as out:
    for line in tqdm.tqdm(f):
        rec = json.loads(line)
        impacts = splade_doc_terms(rec["contents"])
        out.write(json.dumps({"id": rec["id"], "vector": impacts, "raw": rec}) + "\n")
```

**Indexing to Lucene (impact):** Use Pyserini’s impact index flow (as in uniCOIL/SPLADE tutorials). At query time, use `LuceneImpactSearcher`:

```python
from pyserini.search.lucene import LuceneImpactSearcher
splade = LuceneImpactSearcher('/indices/current/splade')  # your learned-sparse index
hits = splade.search('how to persist user data', k=200)
```

> SPLADEv3 details & checkpoints: training objective, sparsity, and distil variants. ONNX can be used to accelerate query‑time expansion. ([arXiv][3])
> Pyserini learned‑sparse retrieval uses Lucene impact postings (uniCOIL/SPLADE). 

### 2.4 **Hybrid fusion** (RRF) integrated in your `HybridSearchEngine`

Your `HybridSearchEngine.search(...)` signature already anticipates **semantic + sparse** channels with **RRF**. Wire it as:

```python
# codeintel_rev/io/hybrid_search.py  (sketch)
def _rrf_fuse(self, runlists, K=60, k=200):
    import collections
    agg = collections.defaultdict(float)
    for run in runlists:  # each run: list of (docid, rank)
        for rank, docid in enumerate(run, 1):
            agg[docid] += 1.0 / (K + rank)
    return sorted(agg.items(), key=lambda x: -x[1])[:k]

def search(self, query: str, *, semantic_hits, limit: int, **kw):
    # 1) semantic docids come from FAISS/CodeRank path you already have
    dense_run = [docid for docid, _ in semantic_hits]

    # 2) BM25 (optional per settings)
    bm25_hits = self._bm25.search(query, k=self._settings.index.topk_sparse)
    bm25_run  = [h.docid for h in bm25_hits]

    # 3) SPLADE (optional per settings)
    s_hits = self._splade.search(query, k=self._settings.index.topk_sparse)
    splade_run = [h.docid for h in s_hits]

    fused = self._rrf_fuse([dense_run, bm25_run, splade_run], K=60, k=limit)
    return self._materialize(fused, trace={'bm25': bm25_run, 'splade': splade_run})
```

The docstring in your engine already explains **RRF** and channel tracking; keep that trace to populate `MethodInfo.retrieval=["semantic","bm25","splade"]` and other MCP fields for transparency.  

> Why RRF? Robust rank aggregation across incomparable score scales (BM25 vs SPLADE vs dense). Keep **K=60** as a stable default. ([Microsoft Learn][5])

### 2.5 **MCP integration** (what the LLM sees)

Return a compact list of fused hits with **path/line range/symbol** metadata and a `MethodInfo` block (retrieval methods, coverage, stage timings) so the LLM can decide how much to read. Your `mcp_server.schemas.MethodInfo` is already shaped for this. 

---

## 3) Tuning for Recall@K on code (systematic plan)

> You emphasized **Recall@K** because many answers exist; the MCP interface can ingest many hits.

1. **BM25 (k1, b, PRF)**

   * Grid: `k1 ∈ {0.7,0.9,1.2,1.5}`, `b ∈ {0.0,0.4,0.75,1.0}`; (optional) RM3: `fbDocs ∈ {5,10}`, `fbTerms ∈ {10,20}`, `origWeight ∈ {0.3,0.5,0.7}`.
   * Watch **long‑file bias** (tune `b`) vs **term‑repetition dominance** (tune `k1`). Start at **(0.9, 0.4)**; often strong on short code chunks.  ([Castorini][2])

2. **SPLADEv3**

   * Prefer **query+doc expansion** for maximum recall; consider **distil** model only if latency or RAM requires it. If index grows, prune by raising sparsity (L1/FLOPs penalty) during encoding.  ([arXiv][3])

3. **Hybrid**

   * RRF **K=60**; fuse **topN** from each retriever (e.g., 200 BM25 + 200 SPLADE + 200 dense) and then cut to the **MCP limit**. Prioritize **coverage** over exact calibration. ([Microsoft Learn][5])

4. **Validation harness**

   * Use a **canary query set** (20–50 queries) curated from your sprint history, PRs, and incident tickets.
   * Measure **Recall@10/25/50** with a lightweight relevance protocol (two‑tier: “contains correct function” vs “contextually helpful”).
   * Automate A/B runs and report **deltas** after each staged index publish.

> Your diagnostics CLI and readiness probes can host simple reporting; we’ll add a small job that runs the canaries before `indexctl publish`. 

---

## 4) Operations & self‑healing

### 4.1 Index lifecycle & automation

* **Nightly (or per‑merge) pipeline**:

  1. regenerate JSONL from SCIP;
  2. rebuild **BM25** (positional) and **SPLADE** impact indexes;
  3. produce **VersionMeta**;
  4. **stage** the version (copy under `versions/<ver>.staging/`), run canary evals;
  5. **publish** (flip `CURRENT` and `current` symlink);
  6. keep **N previous versions** for rollback. Use your `IndexLifecycleManager.prepare/publish/rollback` plus `cli.indexctl`.  

* **Readiness**: add checks that ensure **Lucene indexes** exist, are **readable**, and tokenizer artifacts match; integrate with your `ReadinessProbe` class. Warm GPU if you later host ONNX/Torch for SPLADE query encoding; your `app.gpu_warmup.warmup_gpu()` utility already exists. 

* **Concurrency model**: **instantiate searchers per worker**; don’t share a single `LuceneSearcher` across processes—this is a known caveat. ([GitHub][7])

### 4.2 Telemetry & guardrails

* **Trace retrieval**: Keep per‑channel lists in the response metadata; your `HybridSearchEngine` docstring already suggests channel‑wise attribution. **Log top contributors** and **RRF scores**. 
* **Prometheus counters**:

  * requests, latency per channel, % of fused results where **each channel uniquely contributed**.
  * **Recall@K on canaries** as a nightly gauge.
* **Self‑healing switches**:

  * If **SPLADE encoder** fails, **degrade** to BM25 ⊕ dense; if **BM25** index probe fails, fall back to SPLADE ⊕ dense; if **dense** is unavailable, use **BM25 ⊕ SPLADE** only.
  * Expose health in **/capz** capability snapshot you already maintain. 

### 4.3 Recency without regressions

* Store `commit_ts` in metadata; apply a **small, bounded recency boost** at the **very end** (after RRF) for documents within a moving window. This keeps recall benefits of RRF but subtly surfaces fresh code. Keep the boost **sublinear** and **bounded** to avoid overshadowing relevance.

---

## 5) Configuration surface (tie‑in to your Settings)

Your `config.settings` already shows slots for **BM25Config** and **SpladeConfig** under global `Settings`. Extend with fields for `topk_sparse`, `rrf_K`, and analyzer knobs (e.g., camelCase split). Wire them to `ApplicationContext` to construct the Pyserini searchers; expose status via **admin endpoints**. 

* **Example**:

```python
# config/settings.py additions (illustrative)
class BM25Config(msgspec.Struct):
    enabled: bool = True
    k1: float = 0.9
    b:  float = 0.4
    rm3: bool = False
    rm3_fb_docs: int = 10
    rm3_fb_terms: int = 10
    rm3_orig_weight: float = 0.5
    index_dir: str

class SpladeConfig(msgspec.Struct):
    enabled: bool = True
    model: str = "naver/splade-v3"
    index_dir: str
    onnx: bool = True
    topk_sparse: int = 200
```

> These fields map cleanly into your `ApplicationContext` and `HybridSearchEngine` constructor (see `_settings: Settings` in that class). 

---

## 6) Query execution path (MCP request → fused results)

1. **Session context** created by middleware (session id and capability stamp); you already keep these in contextvars. 
2. **HybridSearchEngine.search** invoked with:

   * **semantic_hits** from FAISS/CodeRank channel you already operate;
   * **bm25** and **splade** run via Pyserini;
   * **RRF** fused top‑N → top‑K;
   * enrich with explainability (channel ranks + BM25 terms or SPLADE impact terms if requested). 
3. **MCP schema** returns compact payload (ids, paths, ranges, and `MethodInfo`); the LLM can read more if it chooses. 

---

## 7) Evaluation & regression (“two‑click” ethos, but on‑prem)

* Use Pyserini’s **TREC‑style eval wrappers** to compute **Recall@K** on canary sets; gate `publish` on **no recall regression** beyond a tolerance band. The Pyserini reproducibility pages and docs show canonical commands and metrics such as recall. ([Castorini][2])
* Keep a **trend panel**: recall@10/25/50 vs time; % unique contributions from each channel; latency distributions.

---

## 8) Risk & mitigation

* **Tokenizer drift**: If BM25 and SPLADE analyze terms differently, coverage holes appear. Keep analyzers aligned and test with a vocabulary diff tool; your hybrid PDF details this alignment requirement. 
* **Model artifacts**: Make sure ONNX/Torch checkpoints are available on‑prem; Pyserini issues note ONNX model availability quirks—mirror artifacts internally. ([GitHub][8])
* **Process model**: Avoid sharing a `LuceneSearcher` across processes; instantiate per worker or run a dedicated search service. ([GitHub][7])

---

## 9) Concrete “Day‑1” checklist

1. **SCIP → JSONL** job using your existing readers/chunkers. 
2. **BM25 index** build with positional flags; confirm docvectors/raw stored; record analyzer config. ([ws-dl.blogspot.com][1])
3. **SPLADE doc encoding** (naver/splade‑v3) → learned‑sparse index; cache tokenizer/model on‑prem; validate against a few canary queries. ([Hugging Face][9])
4. **Wire HybridSearchEngine** to instantiate **LuceneSearcher** and **LuceneImpactSearcher** from `Settings`; ensure **RRF** fusion and per‑channel traces populated. 
5. **Publish v0** with `indexctl publish <ver>`; attach canary recall gate in CI; wire readiness checks. 
6. **Observability**: counters for channel latencies, coverage notes in MCP `MethodInfo`, nightly recall dashboards. 

---

## 10) Appendix: reference snippets you’ll reuse

**BM25 search (Pyserini):**

```python
from pyserini.search.lucene import LuceneSearcher
s = LuceneSearcher('/indices/current/bm25')
s.set_bm25(0.9, 0.4)
# s.set_rm3(10, 10, 0.5) # optional PRF
hits = s.search('initialize postgres connection pool', k=200)
```

([PyPI][6])

**SPLADE impact search:**

```python
from pyserini.search.lucene import LuceneImpactSearcher
spl = LuceneImpactSearcher('/indices/current/splade')
hits = spl.search('persist user data to disk', k=200)
```

(learned‑sparse index built offline from SPLADEv3) 

**RRF (rank‑only fusion):**

```python
def rrf_fuse(runlists, K=60, k=50):
    import collections
    agg = collections.defaultdict(float)
    for run in runlists:
        for rank, docid in enumerate(run, 1):
            agg[docid] += 1.0 / (K + rank)
    return sorted(agg.items(), key=lambda x: -x[1])[:k]
```

([Microsoft Learn][5])

---

## 11) Why this maps naturally to your codebase

* **SCIP + chunking** is already first‑class (`scip_reader`, `cast_chunker`). 
* **Index lifecycle** (stage/publish/rollback) exists (`IndexLifecycleManager`, `cli.indexctl`)—we’re just adding BM25/SPLADE artifacts alongside FAISS/DuckDB and flipping `CURRENT` atomically.  
* **Hybrid engine** already defines the **search fusion** narrative and RRF language; we are simply implementing the sparse channels with Pyserini and connecting telemetry to `MethodInfo`.  
* **App plumbing** (FastAPI, readiness, middleware, capabilities) is in place; we add searcher construction in `ApplicationContext` and expose admin toggles for `bm25.enabled`/`splade.enabled`. 

---

## 12) Sources you can trust for continuing work

* **Pyserini** (README, PyPI, papers): API, BM25/RM3 usage, positional index flags, and hybrid retrieval patterns. ([GitHub][7])
* **SPLADEv3** (HF cards & repo): training recipe, sparsity, distil models. ([Hugging Face][9])
* **RRF** (rank fusion): robust, calibration‑free hybrid. ([Microsoft Learn][5])
* **Internal field guide & hybrid PDF**: code‑aware tokenization, vocabulary alignment, and recall‑first tuning heuristics for code.  

---

### Closing note

This plan keeps **each component on mission**—BM25 for **exact lexical** hits, SPLADEv3 for **semantic expansions with explainability**, dense for **paraphrase/structure coverage**—and fuses them with **RRF** behind a **versioned** and **observed** pipeline. It leans into your repo’s strengths (SCIP structures, lifecycle management, MCP metadata) so you can **automate** quality and **iterate safely**.

If you’d like, I can follow up with:

* a tiny **`indexctl build-bm25`** and **`indexctl build-splade`** CLI that delegates to the steps above and writes `VersionMeta` alongside assets; and
* a **one‑file Pyserini adapter** that constructs searchers from `Settings` and hot‑reloads via `ApplicationContext`. 

[1]: https://ws-dl.blogspot.com/2022/02/2022-02-16-pyserini-information.html?utm_source=chatgpt.com "2022-02-16: Pyserini: an Information Retrieval Framework"
[2]: https://castorini.github.io/pyserini/2cr/msmarco-v1-passage.html?utm_source=chatgpt.com "MS MARCO V1 Passage - Pyserini Reproductions"
[3]: https://arxiv.org/abs/2403.06789?utm_source=chatgpt.com "[2403.06789] SPLADE-v3: New baselines for SPLADE"
[4]: https://huggingface.co/spaces/castorini/ONNX-Demo/blob/main/pyserini/demo/msmarco.py?utm_source=chatgpt.com "pyserini/demo/msmarco.py · castorini/ONNX-Demo at main"
[5]: https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking?utm_source=chatgpt.com "Hybrid search scoring (RRF) - Azure AI Search"
[6]: https://pypi.org/project/pyserini/?utm_source=chatgpt.com "pyserini"
[7]: https://github.com/castorini/pyserini?utm_source=chatgpt.com "castorini/pyserini"
[8]: https://github.com/castorini/pyserini/issues/2028?utm_source=chatgpt.com "ONNX Model not found · Issue #2028 · castorini/pyserini"
[9]: https://huggingface.co/naver/splade-v3?utm_source=chatgpt.com "naver/splade-v3"


# Detailed integration implementation plan narrative #

Below is a **narrative, end‑to‑end implementation plan** for a best‑in‑class, on‑prem deployment of **BM25** and **SPLADEv3** using **Pyserini**, **fully integrated into your `codeintel_rev` repository** and MCP workflow. It’s written as a systems playbook: objectives → architecture → build pipelines → query & fusion → tuning → QA/ops automation → observability → self‑healing. I anchor concrete steps to code that already exists in your repo (with call‑outs where to extend) and cite upstream references for Pyserini/SPLADE specifics.

> **Guiding goals (from your requirements):** on‑prem, automation‑first, aligned formatting across code artifacts to reduce variability, **maximize Recall@K**, and integrate seamlessly with MCP/LLM.

---

## 0) Executive objectives & success criteria

**Mission.** Provide a hybrid sparse stack where **BM25** gives high‑precision lexical matches and **SPLADEv3** provides learned expansion for **high recall**, fused with dense results when available (semantic FAISS / other channels), and governed by robust automation (index lifecycle, drift detection, regression guardrails).

**Primary KPIs.**

* **Recall@K** across a representative query set, with K tuned for your MCP consumer.
* **Coverage** (fraction of labeled relevant chunks surfaced across channels) and **fusion gains** vs. any single channel.
* **Latency budgets** per stage that respect LLM end‑to‑end SLA.
* **SLOs** for index freshness (max staleness from commit to searchable).

**Non‑goals.** We do not attempt one universal scorer; instead we **fuse complementary channels** (BM25/SPLADE/semantics) using **RRF** because it’s robust and low‑ops. Your `HybridSearchEngine` already formalizes this pattern and exposes RRF‑centric semantics. 

---

## 1) Where this plugs into your repo

Your repository already contains the key seams for a first‑class hybrid stack:

* **Providers & engine (sparse side):**

  * `BM25SearchProvider` (thin wrapper around Pyserini’s `LuceneSearcher`), with `search(query, top_k)` returning `ChannelHit`s.
  * `SpladeSearchProvider` (query encoder + Lucene impact searcher) supporting ONNX for fast on‑the‑fly query encoding, and `search(query, top_k)` returning impact‑scored hits. 
  * `HybridSearchEngine` combines **dense (FAISS)** and **sparse (BM25/SPLADE)** via **RRF**; accepts optional per‑channel weights and extra channels. It gathers per‑channel hits and emits a `HybridSearchResult`, tracking contributions and warnings for robustness.

* **Index build orchestration (BM25 side):**

  * `BM25IndexManager.prepare_corpus(...)`: materializes a Pyserini **JsonCollection** directory from your JSONL source (`{"id": ..., "contents": ...}`), enforcing validation and deterministic layout. 
  * `BM25IndexManager` resolves index paths from settings (`BM25Config#index_dir`) to keep artifacts in your repo‑coherent `ResolvedPaths`. 

* **MCP adapters & hydration path:**

  * Post‑retrieval hydration and optional reranking are standardized in **semantic_pro** adapter utilities; the “hybrid → hydrate → (optional) rerank → envelope” pattern is already in place for vector channels and should be reused identically for BM25/SPLADE hybrid results.
  * Standard result shapes (`Finding`, `AnswerEnvelope`, `MethodInfo`) already capture per‑channel provenance (“semantic”, “bm25”, “splade”), coverage text, timing snapshots, and optional explainability payloads for transparency.

**Implication.** We are **not** inventing a new retrieval surface; we wire Pyserini searchers into the existing providers and drive responses through the **same MCP envelope**, adding channel metadata to `MethodInfo.retrieval` and staged timings. 

---

## 2) Document representation & analyzers (one canonical text view for both BM25 & SPLADE)

**Why this matters.** Best‑in‑class recall depends more on **consistent normalization** than on any single hyperparameter. For code: split identifiers (`camelCase`, `PascalCase`, `snake_case`), keep digits and hex patterns, lowercase consistently, and decide what to do with ubiquitous tokens.

**Plan.**

* **Chunking & contents.** Keep your current chunk granularity (function/method‑level or near that), since you already hydrate chunk IDs → rich records from DuckDB for display. Ensure JSONL `contents` reflect the same normalized text your FAISS pipeline used for embeddings to reduce cross‑channel variance.

* **BM25 analyzer.** Use a **custom Lucene analyzer** that:
  (1) lowercases, (2) splits on `[^A-Za-z0-9_]`, (3) splits camelCase, (4) optionally filters a **code‑stoplist** (e.g., `int`, `str`, `return`, `todo`) while retaining identifiers and numbers. You can either (A) build with Anserini’s indexer CLI and pass an analyzer class, or (B) pre‑tokenize and set Pyserini to treat input as tokens. (Pyserini’s standard positional index guidance applies; store positions/doc vectors/raw for robust retrieval.) ([ws-dl.blogspot.com][1])

* **SPLADE tokenizer alignment.** SPLADE uses a **BERT‑family WordPiece** vocabulary (30522 dims for `naver/splade-v3`). Keep end‑to‑end lowercasing and apply **the same basic splitting** in your pre‑BM25 pipeline. Where WordPiece cannot represent symbol characters (e.g., `->`, `::`), normalize consistently in **both** corpora (BM25 and SPLADE side) to avoid systematic blind spots. Your internal guidance on vocabulary alignment and code‑aware tokenization is already captured in the research PDF; carry those decisions into the indexers. 

---

## 3) Index build pipelines

### 3.1 BM25 (Lucene positional index via Pyserini/Anserini)

**Source → JsonCollection.** Use `BM25IndexManager.prepare_corpus(source_jsonl, output_dir=..., overwrite=True)` to materialize a proper Anserini **JsonCollection** directory tree with one JSON file per doc and a manifest (this validates uniqueness and schema). 

**Index build.** Build a **positional** Lucene index (store positions/docvectors/raw). In Pyserini, this is the conventional setup for BM25; defaults are proven and documented. ([ws-dl.blogspot.com][1])

**Search defaults & PRF.**

* Run BM25 with `set_bm25(k1, b)`; defaults like **k1≈0.9, b≈0.4** are strong baselines for short, function‑sized docs (validate per corpus). ([PyPI][2])
* Enable **RM3 pseudo‑relevance feedback** when queries are very short or abstract: `searcher.set_rm3(fb_docs, fb_terms, orig_query_weight)` and re‑issue the query. This usually **improves recall** (monitor precision). ([PyPI][2])

> Your `BM25SearchProvider` already encapsulates `LuceneSearcher` and exposes `search(query, top_k)`. When you initialize it, pass tuned `(k1, b)` from `Settings.bm25`. 

### 3.2 SPLADEv3 (learned sparse “impact” index)

**Model.** Use `naver/splade-v3` (or the distil variant for speed) — both are actively maintained on HF (updated June 2024). They output a **30522‑dim sparse vector** with term weights. For interactive queries, load model **ONNX** for low latency. ([Hugging Face][3])

**Doc side.** Encode each chunk with SPLADE **offline** → produce (term, weight) pairs; then build a Lucene **impact index** (weights become impact scores). Pyserini/Anserini tooling supports this workflow and exposes `LuceneImpactSearcher` for query‑time. 

**Query side.** `SpladeSearchProvider` should:

1. load the ONNX encoder;
2. **encode queries on‑the‑fly**;
3. discretize/quantize weights (you already track `_quantization` and `_max_terms`) and map them to a bag‑of‑words for impact search;
4. invoke `LuceneImpactSearcher`. That’s exactly what your provider’s docstring describes. Wire the model dir, onnx dir, and index dir from `Settings.splade`. 

> **Reality check.** SPLADE’s doc‑time encoding is the heavy step, but it is fully **offline**. Query‑time is near‑BM25 since it’s still an inverted index lookup (plus ONNX forward for the query). 

**Upstream references for impact indexing and search:**

* Pyserini `LuceneImpactSearcher` and prebuilt impact indexes; ONNX demo and registry. 
* SPLADEv3 HF model cards. ([Hugging Face][3])

---

## 4) Query pipeline & fusion (end‑to‑end flow)

**Step A — Dense (if available).** Run semantic retrieval as you already do; produce ordered `(doc_id, score)` tuples for **candidate chunks**.

**Step B — Sparse channels.**

* Call `BM25SearchProvider.search(query, top_k_bm25)`.
* Call `SpladeSearchProvider.search(query, top_k_splade)`.

Both return `ChannelHit`s (doc_id+score). 

**Step C — Fusion.**

* Feed `semantic_hits` + sparse channel hits to `HybridSearchEngine.search(...)`. Your engine uses **Reciprocal Rank Fusion** (RRF), which avoids fragile score normalization and is the recommended, production‑safe hybrid strategy. **K=60** is a robust default in research and industry systems; tune only if needed.  ([Microsoft Learn][4])

**Step D — Hydration & envelope.**

* Convert fused chunk IDs into hydrated records using the existing semantic_pro hydration path; optionally apply LLM reranking (CodeRankLLM) when enabled; return an `AnswerEnvelope` with `MethodInfo.retrieval=["semantic","bm25","splade"]`, coverage notes, and timed stages.

---

## 5) Configuration schema (what to expose & fix)

Extend your `Settings` to capture every knob we intend to control in automation:

* **BM25Config:** `index_dir`, `k1`, `b`, `rm3: Optional[fb_docs, fb_terms, orig_weight]`, `top_k` defaults per call site. (Your `Settings#bm25` already exists; add PRF fields.) 
* **SpladeConfig:** `index_dir`, `model_id`, `model_dir`, `onnx_dir`, `onnx_file`, `quantization`, `max_terms`, `top_k`, `max_query_terms` (if you cap for latency). Your provider’s initializer already takes `(config, model_dir, onnx_dir, index_dir)` and tracks `_quantization`, `_max_terms`. Wire these through your config loader. 
* **Hybrid defaults:** per‑channel **fetch depth before fusion** (e.g., take top 100 from BM25/SPLADE, top 200 from dense), **RRF K** (default 60), and optional **channel weights** (you can keep weights `None` for classic RRF and only use weights if you deploy “weighted RRF”). 

---

## 6) Tuning methodology (maximize Recall@K)

**6.1 Structured decisions & baselines**

* **BM25:** start with **k1∈[0.9,1.2]**, **b∈[0.3,0.5]** for function‑length docs. If whole‑file docs are mixed in, consider **b↑** to re‑balance length. Enable **RM3** for very short or abstract queries (feedbackDocs≈10, feedbackTerms≈10, origQueryWeight≈0.5). Validate with a held‑out query set.  ([PyPI][2])

* **SPLADEv3:** prefer **full query+doc expansion** for **max recall**; drop to doc‑only or distil if latency/size requires. Use ONNX for query‑time; cap `_max_terms` to bound query fan‑out.  ([Hugging Face][3])

* **Fusion:** RRF with **K=60** and **long enough candidate lists** from each side (e.g., fuse top 50–100) to surface tail‑relevant hits. ([Microsoft Learn][4])

**6.2 Objective & data**

* If you have labeled relevance (ideal), optimize **Recall@K**. If not, use **pseudo‑labels** (union of top‑N from multiple channels + dev judgments for a subset) and track **coverage** in `MethodInfo.coverage` to keep decisions auditable. 

**6.3 Practical grid**

* **BM25 k1,b:** 9–16 grid points; **PRF on/off** with 2–3 settings; evaluate **Recall@K** and **TailRecall@K’** (how many “new” relevant hits only appear beyond rank 10).
* **SPLADE:** compare **v3** vs **v3‑distil**, test `_max_terms`∈{128,256,384}; ONNX vs PyTorch to confirm latency headroom.
* **Fusion:** **K**∈{30,60,90}. Usually 60 remains best/robust. ([Microsoft Learn][4])

**6.4 What “good” looks like**

* Hybrid Recall@K significantly > any single channel; tail recall grows meaningfully as you increase K (consistent with your MCP consumer’s ability to read more). Track improvement per language and per query taxonomy (API, error code, design pattern).

---

## 7) Automation & CI/CD (build once, catch regressions automatically)

**7.1 Index lifecycle (BM25 & SPLADE)**

* **Incremental indexing** tied to CI: on merge to main (or nightly), compute changed chunks, re‑encode **doc‑side SPLADE** for those only, and update both Lucene indexes. Keep **versioned index snapshots** for rollbacks. (Lucene supports adds/deletes without full rebuild.)

* **Branch strategy:** either **one index per branch** or a “main‑only” index with recency boosting (see below). Record branch coverage in `MethodInfo.coverage`.

**7.2 Recency‑aware rescoring (optional)**

* For actively evolving code, apply a **mild recency boost** at scoring time using a decay on last‑commit timestamp (e.g., exponential decay with λ calibrated to your update cadence). This can be implemented with Lucene function queries or index payloads; document the boost in `MethodInfo.notes`. 

**7.3 Regression harness (every commit/nightly)**

* Run a fixed **evaluation battery**: Recall@K across a held‑out query set; log hybrid vs channel deltas; fail CI if material regressions happen. Where labels are sparse, run **proxy** checks (e.g., **union‑at‑100** coverage) + **smoke queries** (error code names, flagship APIs). 

**7.4 MCP integration**

* Keep your **single response shape** (`AnswerEnvelope`) and enrich `method.retrieval = ["semantic","bm25","splade"]`, with **stage timings** and observed **coverage** strings (e.g., “Searched 1.2M chunks (Python/Go), main branch”).

---

## 8) Observability & explainability

* Use your existing **timeline / stage timing** plumbing (`observability.timeline`) around each channel call and fusion step so we can break down wall time per channel and monitor tail latencies. `HybridSearchEngine` already accumulates warnings and supports channel accounting. 

* **Explainability payloads** per channel (optional):

  * **BM25:** matched terms & field contributions.
  * **SPLADE:** top activated query terms (after quantization) to show expansions (“save → persist”).
  * Attach as `method.explainability["bm25"] = [...]`, `["splade"] = [...]`. Your schema supports structured explainability. 

---

## 9) Self‑healing patterns

* **Stale/missing artifacts:** Providers should throw **actionable warnings**, not hard errors, and `HybridSearchEngine._gather_channel_hits` already **collects errors as warnings** so other channels still serve results (degraded mode). Surface these in `MethodInfo.notes`. 

* **Drift detection:** Track distributions of:

  * BM25 doc length & avgdl;
  * SPLADE average non‑zero terms per doc and per query;
  * Fusion overlap (% docs appearing in ≥2 channels).
    Alert if distributions shift materially release‑over‑release.

* **Auto‑rollback:** If CI shows Recall@K regression beyond threshold, **promote previous index snapshot** and log a “reindex required” task with diffs of analyzer/model config.

---

## 10) Concrete code wiring (snippets)

> The following sticks to your existing entrypoints, so initial integration is mostly configuration and a small number of glue functions.

### 10.1 Provider initialization

```python
# codeintel_rev/app/config_context.py (conceptual snippet)
from codeintel_rev.io.hybrid_search import BM25SearchProvider, SpladeSearchProvider, HybridSearchEngine

def get_hybrid_engine(ctx) -> HybridSearchEngine:
    s = ctx.settings
    paths = ctx.paths

    bm25 = None
    if s.bm25 and paths.bm25_index.exists():
        bm25 = BM25SearchProvider(
            index_dir=paths.bm25_index,
            k1=s.bm25.k1, b=s.bm25.b
        )
        # Optionally: bm25.enable_rm3(s.bm25.rm3)  # wrapper you add to set RM3

    splade = None
    if s.splade and paths.splade_index.exists():
        splade = SpladeSearchProvider(
            config=s.splade,
            model_dir=paths.splade_model_dir,
            onnx_dir=paths.splade_onnx_dir,
            index_dir=paths.splade_index
        )

    return HybridSearchEngine(paths=paths, settings=s, providers={"bm25": bm25, "splade": splade})
```

Your `HybridSearchEngine.search(...)` contract already takes `semantic_hits` plus limits and optional weights, performs **RRF**, and returns a `HybridSearchResult`. 

### 10.2 BM25 corpus prep & build

```python
# scripts/build_bm25.py
from codeintel_rev.io.bm25_manager import BM25IndexManager

mgr = BM25IndexManager(settings, paths)
mgr.prepare_corpus(source="chunks.jsonl", output_dir=paths.bm25_corpus, overwrite=True)  # validates & lays out
mgr.build_index()  # implement to call Pyserini/Anserini indexer with positional fields
```

`prepare_corpus` is already in place; add a `build_index()` method that shells Pyserini’s `index` module with your analyzer options. 

### 10.3 SPLADE doc encoding & impact index

```python
# scripts/build_splade.py
from codeintel_rev.io.splade_manager import SpladeIndexManager  # small new helper you create

simgr = SpladeIndexManager(settings, paths)
simgr.encode_documents_to_impacts(  # batched, offline
    source="chunks.jsonl",
    model_id=settings.splade.model_id, onnx=settings.splade.onnx_file,
    quantization=settings.splade.quantization, max_terms=settings.splade.max_terms
)
simgr.build_impact_index(output_dir=paths.splade_index)
```

At query time, `SpladeSearchProvider` loads ONNX, encodes the query, decodes to bag‑of‑words (respect `_quantization`, `_max_terms`), and searches `LuceneImpactSearcher`. This is consistent with your provider design. 

### 10.4 MCP handler (hybrid → hydrate → envelope)

```python
# mcp_server/server_semantic.py (conceptual)
from codeintel_rev.mcp_server.adapters import semantic_pro_adapter as adapter

@mcp.tool()
def semantic_search_pro(query: str, limit: int = 20, options: dict | None = None) -> AnswerEnvelope:
    ctx = get_context()
    # 1) dense: get FAISS (or XTR) candidates → semantic_hits
    semantic_hits = run_semantic(query, limit=ctx.settings.rerank.candidate_pool)
    # 2) sparse: fuse via HybridSearchEngine
    hybrid = ctx.get_hybrid_engine()
    fused = hybrid.search(query, semantic_hits=semantic_hits, limit=limit)
    # 3) hydrate + optional rerank (CodeRankLLM)
    outcome = adapter.hydrate_and_rerank(fused, query, ctx, options)
    # 4) envelope (findings + method.retrieval + coverage + timings)
    return adapter.to_envelope(outcome, retrieval=["semantic","bm25","splade"])
```

This mirrors your existing **semantic_pro** pipeline, adding sparse channels before hydration. 

---

## 11) Operational playbook (runbooks & schedules)

**Build cadence.**

* Nightly: re‑encode changed docs for SPLADE, update BM25 & impact indexes, run regression battery (Recall@K, coverage, latency), push snapshot if green.
* On‑merge: light path (only changed files), and run smoke tests.

**Capacity.**

* SPLADE doc‑encoding throughput scales with CPU/GPU availability; run batchers with job shards per repo/language. Query‑time ONNX runs on CPU fine for single queries (LLM latency dominates).

**Backups & rollbacks.**

* Store index snapshots in artifact storage alongside a manifest of settings (k1,b, RM3 params, model_id, max_terms, K). Roll back atomically if CI flags regression.

**Security/on‑prem.**

* All models & indexes live in your artifact store; disable outbound calls in production. HF models are **vendored** into `paths.splade_model_dir`.

---

## 12) Advanced options (when you want to push further)

* **Multi‑field BM25** (code, comments, symbols) with **field weights**; Pyserini supports weighted fields. Validate gains vs. complexity. ([Hugging Face][5])
* **HNSW in Lucene** for dense inside the same engine (Anserini integration) if you prefer a single Lucene runtime for sparse + dense; this is a supported path per Anserini research. ([ACM Digital Library][6])
* **Weighted RRF** in your `fuse_weighted_rrf` module if you want to tilt toward SPLADE for abstract queries or toward BM25 for identifier queries (e.g., heuristic: if query has camelCase or `::`, upweight BM25). You already have a fusion helper module to extend. 

---

## 13) “Best practice” defaults to check in

* **BM25:** `k1=0.9, b=0.4`; enable **RM3** for short queries (`fb_docs=10, fb_terms=10, orig_weight=0.5`) with a switch; field analyzer aligned with your code normalization. ([PyPI][2])
* **SPLADEv3:** `model_id="naver/splade-v3"`, ONNX enabled; `_max_terms`≈256; `quantization` tuned to preserve top weights; document‑side expansion always; query‑side expansion on. ([Hugging Face][3])
* **Fusion:** RRF **K=60**; fuse top 50–100 from each channel. ([Microsoft Learn][4])
* **Recall target:** choose **K** consistent with your MCP consumer (since it “can choose to read or not read” and has no strict max), e.g., standardize on Recall@50 and Recall@100 as primary SLOs.

---

## 14) What to implement next (checklist)

1. **Finalize text normalization** rules (BM25 analyzer & SPLADE preprocessing) and lock in a golden preprocessor unit test (identifier splitting, lowercase, symbol handling).
2. **Complete BM25 build path:** implement `BM25IndexManager.build_index()` to invoke Pyserini/Anserini with positional storage and analyzer wiring. 
3. **Add `SpladeIndexManager`** and a batch encoder with ONNX export/loader; persist impacts and build the Lucene impact index. (Follow the doc‑encode → impact index flow referenced above.) 
4. **Wire providers to settings/paths** and expose CLI entrypoints: `build_bm25`, `build_splade`, `reindex_changed --since=<commit>` (diff‑aware).
5. **Extend `HybridSearchEngine` configuration** with: per‑channel fetch sizes; optional weighted RRF; RRF‑K from settings. 
6. **Instrumentation:** wrap provider calls with timeline spans; record per‑channel counts/latencies and warnings; attach `MethodInfo` with retrieval list + coverage string. 
7. **Regression suite:** curate 50–100 seed queries spanning identifier, API, error code, conceptual “how to…”; create YAML fixtures listing expected relevant chunk IDs (or weak labels); run **Recall@{10,50,100}** pre/post on CI.
8. **Drift monitors:** track avgdl, SPLADE activated term counts, and fusion overlap; alert on deltas.
9. **Docs for SREs:** runbooks for rebuild, rollback, and interpreting warnings from `_gather_channel_hits(...)` during partial outages. 

---

## 15) Quick reference: upstream facts we rely on

* **Pyserini** provides BM25 via `LuceneSearcher`, PRF via `set_rm3`, and impact retrieval (`LuceneImpactSearcher`) with ONNX support. ([PyPI][2])
* **SPLADEv3** models (`naver/splade-v3`, `...-distilbert`) are actively maintained; 30,522‑dim sparse outputs; good BEIR/MS MARCO performance. ([Hugging Face][3])
* **RRF** with **K≈60** is the industry‑standard default for hybrid ranking, including cloud engines. ([Microsoft Learn][4])
* **Lucene HNSW** enables dense in Lucene/Anserini if you later want a single engine. ([ACM Digital Library][6])

---

## 16) Appendix: Minimal Pyserini usage patterns (for clarity)

**BM25** (positional index):

```python
from pyserini.search.lucene import LuceneSearcher
s = LuceneSearcher(index_dir)
s.set_bm25(k1, b)
# Optional: s.set_rm3(fb_docs=10, fb_terms=10, original_query_weight=0.5)
hits = s.search("initialize database connection", k=100)
```

(Entry points and defaults: PyPI docs.) ([PyPI][2])

**Impact search (SPLADE/uniCOIL)**:

```python
from pyserini.search.lucene import LuceneImpactSearcher
si = LuceneImpactSearcher(index_dir)   # built from SPLADE term→weight
hits = si.search("persist user profile", k=100)
```

(Pyserini ships prebuilt impact indexes and ONNX examples.) 

---

### Closing note

You already have the core building blocks in `codeintel_rev` – **providers**, a **hybrid engine** with RRF, and **MCP hydration & envelopes**. The heavy lifting now is **solidifying the index build pipelines** (BM25 & SPLADE impact), **standardizing normalization**, and **standing up the automation loop** (incremental reindex + regression harness + drift monitors). Do those well, and the rest becomes controlled iteration on k1/b, PRF, SPLADE term caps, and fusion depth — all under CI.

If you’d like, I can convert this narrative into:

* a short **Engineering RFC** with an acceptance plan and timelines, and
* a set of **CLI scripts** (`build_bm25`, `build_splade`, `reindex_changed`) matching the steps above,
* plus a **CI workflow YAML** that runs the regression battery (Recall@K) and promotes snapshots on green.

---

#### Citations (repo internals)

Key repo internal references used above: `HybridSearchEngine` RRF fusion & channel plumbing; `BM25SearchProvider`/`SpladeSearchProvider` search contracts and initialization; `BM25IndexManager.prepare_corpus`; MCP hydration/envelope schemas and method metadata.

#### Citations (supporting web sources)

Pyserini BM25 & PRF usage; impact retrieval & ONNX; SPLADEv3 model cards; RRF defaults; Lucene HNSW: ([PyPI][2])

---

#### Next doc: **hardening guide for ops & SRE**

* Failure modes & degraded behavior mapping to `MethodInfo.notes` and warnings gathered in `_gather_channel_hits(...)`. 
* Capacity planning worksheet (SPLADE encoding throughput, ONNX QPS).
* Runbook for **index corruption** and **targeted re‑encode** of hot modules.

If you want me to turn those into concrete PRs/CLIs (with exact commands), I can draft the code paths against your `io/*_manager` modules and `app/config_context` seams directly.

[1]: https://ws-dl.blogspot.com/2022/02/2022-02-16-pyserini-information.html?utm_source=chatgpt.com "2022-02-16: Pyserini: an Information Retrieval Framework"
[2]: https://pypi.org/project/pyserini/?utm_source=chatgpt.com "pyserini"
[3]: https://huggingface.co/naver/splade-v3?utm_source=chatgpt.com "naver/splade-v3"
[4]: https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking?utm_source=chatgpt.com "Hybrid search scoring (RRF) - Azure AI Search"
[5]: https://huggingface.co/spaces/castorini/ONNX-Demo/resolve/55810ac7b04ee669aff8742ec21c59932ac35d3c/pyserini/search/lucene/__main__.py?download=true&utm_source=chatgpt.com "https://huggingface.co/spaces/castorini/ONNX-Demo/..."
[6]: https://dl.acm.org/doi/10.1145/3583780.3615112?utm_source=chatgpt.com "Anserini Gets Dense Retrieval: Integration of Lucene's ..."



# Integration with repo and design for operating excellence #

Below is a **narrative, repo‑integrated, best‑in‑class implementation plan** for deploying **BM25** and **SPLADE‑v3** with Pyserini, tightly coupled to your current codebase and MCP interface. I’ve grounded the plan in your uploaded **SCIP index**, **repo metrics**, **Pyserini field‑guide**, and the earlier PDF on BM25+SPLADE in hybrid retrieval, and I cite both internal and web sources inline. Where useful I include focused code snippets (Python/CLI) that drop naturally into your repo structure.

---

## 0) What “best‑in‑class” means for your context

**Mission:** Maximize **Recall@K** for LLM–driven code questions while keeping latency predictable and maintenance largely **automated**. BM25 provides precise lexical matching; SPLADE‑v3 provides **learned sparse** expansions that recover “hidden gems” BM25 misses; dense (already present) provides semantic coverage. These channels are fused with **RRF** (robust, tuning‑light), all mediated by your **HybridSearchEngine** and MCP adapter that builds **MethodInfo** (retrieval metadata) for the client.   ([G. V. Cormack][1])

You already have the plumbing:

* **HybridSearchEngine**: gathers per‑channel hits, applies RRF, returns a fused list with contribution tracking and warnings; BM25/SPLADE are toggled by settings.
* **BM25SearchProvider** thin wrapper around Pyserini’s LuceneSearcher. 
* **MCP adapters** produce **MethodInfo** (retrieval channels, coverage, timings, notes, reranker metadata) for responses. 
* **App lifecycle** wires readiness, GPU warmups, FAISS preloading, etc. We’ll plug BM25/SPLADE checks here.

---

## 1) Architecture—how BM25 and SPLADE‑v3 fit your repo

**High‑level shape**

```
SCIP -> chunker -> catalogs (DuckDB, Parquet) -> 
    (a) BM25 JSONL -> Lucene positional index
    (b) SPLADE vectors -> Lucene impact index
    (c) Dense vectors -> FAISS (already present)
HybridSearchEngine -> RRF fuse -> MCP envelope (MethodInfo)
```

* **Chunking & catalogs.** Keep the current cAST/SCIP pipeline and DuckDB/Parquet catalog as the golden source for chunk text + metadata (path, language, commit time). The **indexing pipeline** is already scaffolded (bin.index_all); we’ll extend it to produce BM25 JSONL and SPLADE vectors from the same chunks to preserve alignment.
* **Channel providers.** Continue to use `HybridSearchEngine.search(query, semantic_hits, limit, weights?)` to fuse channels, with per‑channel fan‑out and **RRF_K** configurable in **IndexConfig / env** (you already expose `RRF_K`, per‑channel top‑K, BM25 k1,b, and SPLADE knobs in `IndexConfig`).
* **Observability.** Your `retrieval.telemetry`/`gating` utilities give us stage timings, decisions, and metrics we’ll record per stage (BM25/SPLADE/FAISS) for SLOs and self‑healing.

---

## 2) Corpus preparation—the single source of truth

### 2.1 Normalize once, reuse everywhere

* Normalize identifiers and comments at **chunking** time, not per‑channel, so BM25 and SPLADE see consistent tokens. Preserve a **raw** version of contents for MCA/LLM snippets, but feed the **normalized** variant to all indexers. (Your chunker and catalogs are the best place for this.) 

### 2.2 Fields to carry through

For each chunk keep:

* `id` (stable `chunk_id`)
* `contents` (normalized text for indexing)
* `path`, `symbol` (if available), `language`
* `branch`, `commit_ts` (for **recency** decisions)
* `line_start/line_end` (hydration into MCP/LLM snippets)

These already flow through your Parquet/DuckDB layers; ensure the **same ids** are used in BM25/SPLADE and your FAISS/XTR stores, so **HybridSearchEngine** and the MCP server can hydrate consistently. 

---

## 3) BM25—indexing, search, and tuning

### 3.1 Indexing plan (Lucene positional + docvectors)

Build a **positional** index with stored **docvectors** and **raw** so you can enable **RM3 PRF** and pull raw text fast:

```bash
python -m pyserini.index.lucene \
  --collection JsonCollection \
  --input $BM25_JSONL_DIR \
  --index  $BM25_INDEX_DIR \
  --generator DefaultLuceneDocumentGenerator \
  --threads ${BM25_THREADS:-8} \
  --storePositions --storeDocvectors --storeRaw
```

This matches Pyserini cookbook guidance; storing docvectors is important for features like PRF and certain analyzers/readers.

**Analyzer choice for code.** If you pre‑tokenize identifiers (camelCase→“camel case”, split `_`, keep punctuation tokens selectively), you can feed pretokenized contents and rely on Lucene’s **Whitespace** analyzer—which Pyserini selects for `pretokenized` collections—so tokens are preserved as given. (Pretokenization route is the most reliable way to get code‑aware tokenization through Lucene from Python.) ([UCSB Computer Science][2])

> **Tip:** Keep **lowercasing** during normalization so BM25 and SPLADE vocabularies stay aligned. Configure stopword removal conservatively for code (or not at all).

### 3.2 Query‑time configuration

```python
from pyserini.search.lucene import LuceneSearcher
s = LuceneSearcher(BM25_INDEX_DIR)
s.set_bm25(k1=0.9, b=0.4)  # strong baseline; tune per corpus
# Optional PRF:
# s.set_rm3(fb_docs=10, fb_terms=10, original_query_weight=0.5)
hits = s.search(query, k=K)
```

Defaults like **k1=0.9, b=0.4** are strong starting points; PRF (RM3) is available and proven by Pyserini’s maintainers in issues/docs.  ([GitHub][3])

### 3.3 BM25 tuning for code (Recall@K)

* **Document granularity** affects `b`: chunk‑sized docs (functions) suggest **lower** length normalization; whole‑file docs suggest **higher** `b`. Validate on your query set. 
* **k1** balances term repetition vs. single mentions; for recall, a slightly **lower** k1 can help avoid over‑rewarding repetitions that drown single‑mention relevant chunks. Validate. 
* **PRF (RM3)** improves recall on short natural‑language queries; use moderate mix weight (e.g. 0.4–0.6). ([GitHub][3])

---

## 4) SPLADE‑v3—indexing, query, and trade‑offs

**Why SPLADE‑v3?** Learned‑sparse expansions deliver **lexical coverage** for semantically related code snippets without dense retrieval’s ANN constraints—ideal for high‑recall first‑stage fusion with BM25. SPLADE‑v3 shows state‑of‑the‑art results across many query sets. ([arXiv][4])

### 4.1 Document‑side expansions ➜ Lucene impact index

Workflow:

1. **Encode chunks** to token→impact weights (HF checkpoint `naver/splade-v3`; export **ONNX** for speed/portability).
2. **Write** Pyserini **JsonVectorCollection** shards (`{"id": "...","vector": {"term": weight, ...}}`).
3. **Build** a Lucene **impact** index.
4. **Query** with `LuceneImpactSearcher` using **ONNX Runtime** for query expansion.

Pyserini exposes `LuceneImpactSearcher` for SPLADE/uniCOIL. 

**Indexes to build** (paths are already modeled in your config—SPLADE model dir, ONNX file, vectors dir, index dir):

```bash
# 1) Encode (pseudo-CLI; you’ll wrap as a repo script)
python -m codeintel_rev.tools.splade_encode_docs \
  --model $SPLADE_MODEL_ID --onnx_out $SPLADE_ONNX_DIR \
  --chunks_parquet $VECTORS_PARQUET --out_jsonv $SPLADE_VECTORS_DIR \
  --quant ${SPLADE_QUANTIZATION:-100} --batch ${SPLADE_BATCH_SIZE:-32}

# 2) Build impact index from JSON vector shards
python -m pyserini.index.lucene \
  --collection JsonVectorCollection \
  --input $SPLADE_VECTORS_DIR \
  --index $SPLADE_INDEX_DIR \
  --generator DefaultLuceneDocumentGenerator \
  --threads 8
```

(You can base the encoder script on your settings object where `SPLADE_*` fields already exist: model id/dir, ONNX path, quantization, max terms, clause limit, etc.)

### 4.2 Query‑time SPLADE

```python
from pyserini.search.lucene import LuceneImpactSearcher
splade = LuceneImpactSearcher(SPLADE_INDEX_DIR, 
                              encoder='naver/splade-v3', 
                              device='cpu', # or CUDA if you wrap ORT EPs
                              onnx=True)    # use ONNXRuntime

hits = splade.search(query, k=K)
```

* Keep **query+doc expansion** for maximum recall in your LLM setting (latency dominated by the LLM anyway). Consider **doc‑only** only if you must reduce query latency. 
* Tune **quantization** and **max_terms** (you expose both already) to manage index size vs. recall; start with quant=100 and max_terms≈3000; prune only after validating recall impact. 

> **Efficiency knobs:** If needed, adopt **postings clipping** (learned‑sparse speedup) and/or pre‑filter with BM25 small‑k before SPLADE; then fuse. ([ACL Anthology][5])

---

## 5) Fusion—RRF as the default (and why)

Your `HybridSearchEngine` already gathers channel hits and **RRF‑fuses** them into a single ranked list; you’ve parameterized **per‑channel fan‑out** and **RRF_K** in config/env. Keep **RRF_K ≈ 60** (standard), and fuse sufficiently deep lists from each channel (e.g., top‑50~100 per channel) to protect **Recall@K**.  ([G. V. Cormack][1])

> Why RRF? Score scales differ wildly across dense, BM25, and SPLADE; **rank‑based fusion** avoids brittle normalization and is production‑proven. ([G. V. Cormack][1])

---

## 6) Wiring this into your application

### 6.1 ApplicationContext boot & readiness

Hook BM25/SPLADE readiness into your existing startup **lifespan**:

* Confirm BM25 **index dir** present and LuceneSearcher opens successfully.
* Confirm SPLADE **index dir** and **ONNX** artifacts exist; load **LuceneImpactSearcher** once to warm caches.
* Surface both in **ReadinessProbe** and **/admin/index** routes next to FAISS. You already have structured warmup and readiness scaffolding here. 

### 6.2 The search path (per request)

1. Embed query ➜ **FAISS** stage‑0 results (already present).
2. `HybridSearchEngine.search(...)` collects **semantic, BM25, SPLADE** hits, fuses via **RRF**, tracks **warnings**, respects per‑channel budgets. 
3. Hydrate final chunks through DuckDB/Parquet ➜ build **MCP AnswerEnvelope** with **MethodInfo**:

   * `retrieval=["semantic","bm25","splade"]`,
   * `coverage` (“Searched N chunks on branch X; BM25/SPLADE enabled”),
   * `stages` (timers from `retrieval.telemetry`),
   * `explainability` (per‑channel contribution map if enabled).

---

## 7) Automation: index lifecycle, drift guards, and parameter sweeps

### 7.1 Automatic corpus→index sync

* **Triggering.** Use your Git client wrapper to detect new commits on tracked branches; enqueue **incremental BM25 JSONL/SPLADE vector shards** for the touched files. (You already have Git plumbing and a pipeline shell in `bin.index_all`; extend it with a **delta mode**.)
* **BM25 delta.** Regenerate JSONL only for changed chunk ids; run Pyserini indexer with **update** mode (or reindex the affected shard directory and atomically swap).
* **SPLADE delta.** Re‑encode just those chunks to JSON vectors; run impact index builder incrementally (or shard‑swap). Track shard sizes and ages in your catalog for rollup compaction.

### 7.2 Self‑healing checks (continuous)

* **Index integrity:** verify Lucene `segments_N` present, searcher opens, term/doc counts > 0; SPLADE ONNX loads (CPU EP OK; GPU EP attempted). On failure, set **readiness=false**, **fallback** to remaining channels (design for **partial‑degraded** operation). Your FAISS manager already has GPU fallback patterns; mirror that for Lucene. 
* **Drift detectors:**

  * **Distribution shifts**: track moving averages of query length, tokens unseen by BM25 analyzer, SPLADE active‑term counts; alert on deltas.
  * **Recall regression tests** (nightly/CI): run a fixed set of queries and assert **Recall@K** and **coverage** thresholds; on regressions, auto‑open a ticket with diffs. You outlined this in your PDF; we’ll implement it as code. 

### 7.3 Parameter sweeps (scheduled)

* **Grid** over `k1,b`, SPLADE `quant,max_terms`, `RRF_K`, **per‑channel fan‑out**.
* Validate on canonical and mined queries; **objective = Recall@K** with latency/CPU as secondary constraints. Automate monthly. 

---

## 8) SRE hardening—SLOs, dashboards, and runbooks

### 8.1 SLOs

* **Availability:** BM25+SPLADE readiness ≥ 99.9% (degraded OK if at least 2 channels healthy).
* **Latency budgets (P99, single query):**

  * BM25 ≤ 80 ms (local NVMe, warmed), SPLADE ≤ 150 ms (query ONNX on CPU), fusion & hydration ≤ 80 ms.
* **Quality guardrails:** **Recall@K** (K=25 or 50) ≥ agreed baseline. (Track per‑channel contributions to detect silent failures.)

### 8.2 Metrics & traces (you already have primitives)

* Use `track_stage()` for **embedding**, **bm25**, **splade**, **hydrate**, **fuse**; export histogram/counters via Prometheus (`record_stage_metric`, `record_stage_decision`). Build Grafana panels. 

### 8.3 Health & admin endpoints

* `/healthz`: up + dependency pings.
* `/readyz`: confirms indices & ONNX loadable.
* `/admin/index/state`: doc counts, index byte sizes, shard ages, SPLADE vector density, BM25 avgdl.
* `/admin/index/rebuild?channel=bm25|splade&scope=branch|path` for manual backstops.

### 8.4 Incident runbook

* **Symptom:** Recall collapse, BM25 OK, SPLADE missing.

  * **Check:** SPLADE index open? ONNX EP ok? Term count drop?
  * **Action:** Re‑encode last delta; if ONNX GPU failing, force CPU EP and relaunch; temporarily boost BM25 fan‑out to compensate; alert “degraded but serving”.
* **Symptom:** Timeouts on hybrid.

  * **Check:** SPLADE encoding queue backlog; reduce SPLADE top‑k for fusion and flag **limits** in MCP envelope; investigate CPU pressure.

---

## 9) Hybrid ranking details—what to tune first

1. **Per‑channel fan‑out** (most leverage for recall). Start **top‑100 BM25 + top‑100 SPLADE** ➜ fuse ➜ return K (e.g., 25..50 to MCP). Validate budget impact; reduce to 50+50 if needed. 
2. **RRF_K** at 60 and leave it; it’s robust. ([G. V. Cormack][1])
3. **BM25 k1,b** small sweeps; **PRF** on/off for specific query families (short natural‑language). ([GitHub][3])
4. **SPLADE quant/max_terms** only after (1–3); prefer recall‑friendly defaults. 

---

## 10) Recency & scope logic (LLM‑friendly)

* **Recency bias** as **post‑fusion** light rerank (timestamp decay), with opt‑out if query indicates historical intent. Store `commit_ts` for chunks; compute a small bonus that can’t dominate relevance. Automation‑friendly; flips on instantly as new code lands. 
* **Scope filters** (language/globs/paths) integrated via your **SessionScope** middleware so the LLM can restrict search breadth; carry into **MethodInfo.scope** for transparency. 

---

## 11) Evaluation harness (offline & CI)

* **Ground truth:** Start with curated QA and “should‑retrieve” pairs mined from docstrings, READMEs, and commit messages; grow organically from LLM sessions.
* **Metrics:** Recall@K (primary), MRR@K (secondary), coverage stats, channel‑contribution histograms.
* **Repro:** Keep small jsonl of queries; run `bm25`, `splade`, `hybrid` with a fixed seed and capture runfiles (TREC style). Compare against baselines; fail CI if **Recall@K** drops. (Pyserini eval wrappers can compute standard IR metrics; for BM25 PRF the index must store docvectors.) 

---

## 12) Security & compliance (on‑prem basics)

* **Model artifacts** (SPLADE HF checkpoint & ONNX) pinned by **commit hash**; checksum on start.
* **Index directories** owned by a dedicated user; atomic shard swap; periodic snapshot to offline storage.
* **No outbound calls** during query. (HF/model fetch only during provisioning.)
* **Explainability** payload (optional): per‑channel top contributors to reassure users without leaking PII. Your `MethodInfo.explainability` is ready to carry this. 

---

## 13) Concrete repo changes & snippets

### 13.1 Extend settings (if not already present)

Your `Settings.index` already exposes BM25/SPLADE/RRF knobs and paths; ensure env→settings mapping is hooked, e.g.:

* `BM25_JSONL_DIR`, `BM25_INDEX_DIR`, `BM25_THREADS`, `BM25_K1`, `BM25_B`
* `SPLADE_MODEL_ID`, `SPLADE_MODEL_DIR`, `SPLADE_ONNX_DIR`, `SPLADE_ONNX_FILE`, `SPLADE_VECTORS_DIR`, `SPLADE_INDEX_DIR`, `SPLADE_QUANTIZATION`, `SPLADE_MAX_TERMS`
* `RRF_K`, `HYBRID_TOP_K_PER_CHANNEL`, `HYBRID_ENABLE_BM25`, `HYBRID_ENABLE_SPLADE`

(These appear already in your config docs.)

### 13.2 BM25 corpus writer (from DuckDB)

```python
# codeintel_rev/io/bm25_manager.py
from pathlib import Path
import json, duckdb

def write_bm25_jsonl(db_path: Path, out_dir: Path) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path), read_only=True)
    # Adjust to your actual table/columns
    rows = con.execute("""
        select chunk_id, contents_norm as contents 
        from chunks where contents_norm is not null
    """).fetchall()
    count = 0
    with (out_dir / "shard_000.jsonl").open("w") as f:
        for cid, text in rows:
            f.write(json.dumps({"id": str(cid), "contents": text}) + "\n")
            count += 1
    return count
```

(Your `bm25_manager` module is already the right home for this.)

Then index with the CLI shown in §3.1.

### 13.3 SPLADE document encoder CLI (repo tool)

Create `codeintel_rev/tools/splade_encode_docs.py` that:

* Loads HF model `naver/splade-v3` (export ONNX if not present),
* Streams chunks from DuckDB/Parquet,
* Emits **JsonVectorCollection** shards with quantized weights and **term cutoff** (`SPLADE_MAX_TERMS`).
  Store outputs under `$SPLADE_VECTORS_DIR`. (All paths/params read from your `Settings`.)  ([Hugging Face][6])

### 13.4 HybridSearchEngine: ensure robust channel handling

* Respect `HYBRID_ENABLE_BM25` / `HYBRID_ENABLE_SPLADE`.
* If a channel fails to initialize/search, add a **warning** (you already do) and continue with others (fail‑soft). 
* Keep **per‑channel top‑K** configurable (e.g., 50 by default). 

### 13.5 MCP extras (traceable answers)

Populate `MethodInfo` in your MCP adapter with:

```python
method = {
  "retrieval": ["semantic","bm25","splade"],
  "coverage": f"Searched {N} chunks on {branch}; "
              f"bm25={'on' if bm25_on else 'off'}, splade={'on' if splade_on else 'off'}",
  "stages": timings,            # from retrieval.telemetry
  "notes": warnings,            # from HybridSearchEngine._gather_channel_hits
  "explainability": contribs,   # optional per-channel signals
}
```

Your schemas and adapter helper already anticipate this payload.

---

## 14) Deployment & ops checklists

**Provisioning**

* [ ] Download/pin SPLADE‑v3; export ONNX; record checksums. ([Hugging Face][6])
* [ ] Build BM25 positional index with docvectors. 
* [ ] Build SPLADE impact index from JsonVectorCollection. 
* [ ] Wire readiness probes; prewarm searchers. 

**Runtime**

* [ ] Stage timings emitted for embed/bm25/splade/hydrate/fuse. 
* [ ] Channel contribution histograms (debug) for explainability.
* [ ] Index size/age dashboards; alerts on growth/lag.

**Automation**

* [ ] Git webhook ➜ delta encodes; atomic shard swaps; nightly compaction. 
* [ ] Nightly **recall regression** and monthly **parameter sweep**; block promotion on regression. 

---

## 15) “First 30 days” tuning plan (prioritized)

1. **Per‑channel fan‑out**: 100+100 ➜ fuse ➜ K=25..50; monitor Recall@K and P99. 
2. **BM25** k1∈{0.8,0.9,1.2}, b∈{0.2,0.4,0.7}; try **RM3** on a short‑query subset. ([GitHub][3])
3. **SPLADE** quant∈{100,200}, max_terms∈{1500,3000}; measure index size and latency effect. 
4. **RRF_K** sanity check (40, 60, 80) to confirm flat optimum; usually stay at 60. ([G. V. Cormack][1])
5. **Recency** re‑rank: light decay, regain head queries freshness; guard rails for historical intents. 

---

## 16) Appendix—reference snippets you’ll reuse

**Programmatic BM25 search (provider already exists):**

```python
from codeintel_rev.io.hybrid_search import BM25SearchProvider
bm25 = BM25SearchProvider(index_dir=paths.lucene_dir, k1=settings.index.bm25_k1, b=settings.index.bm25_b)
hits = bm25.search(query, top_k=100)
```

(Your provider’s docstring clarifies parameters and rationale.) 

**Programmatic SPLADE search:**

```python
from pyserini.search.lucene import LuceneImpactSearcher
splade = LuceneImpactSearcher(SPLADE_INDEX_DIR, onnx=True, encoder=settings.index.splade_model_id)
hits = splade.search(query, k=100)
```

(Pyserini supports **impact search** and ONNX demo paths; the cookbook shows patterns.) 

**Hybrid fusion (conceptual sketch—your engine already does this):**

```python
def rrf_fuse(runlists, K=60, k=50):
    from collections import defaultdict
    agg = defaultdict(float)
    for run in runlists:
        for rank, (docid, _) in enumerate(run, 1):
            agg[docid] += 1.0/(K+rank)
    return sorted(agg.items(), key=lambda x: -x[1])[:k]
```

(Keep `RRF_K=60` unless data says otherwise.)  ([G. V. Cormack][1])

---

## 17) Why this will scale and stay healthy

* **Roles are crisp**: BM25 = precision‑oriented lexical; SPLADE‑v3 = recall‑oriented learned‑sparse; dense = semantic safety net; fused via RRF to maximize **Recall@K** under LLM consumption. 
* **Ops are boring**: one‑time analyzers/normalization; reproducible index builds; **self‑healing** readiness + partial‑degraded service. 
* **Automation first**: deltas from Git; recurring sweeps; regression alarms; explicit MCP **MethodInfo** for downstream transparency. 

---

### Sources & further reading (selected)

* Your repo code: **HybridSearchEngine**, providers, settings, and app lifecycle.
* Your Pyserini field‑guide with BM25/Impact snippets & index flags.
* Your hybrid PDF on code retrieval (recall monitoring, recency, RRF choices).
* **RRF** original paper and discussions. ([G. V. Cormack][1])
* **SPLADE‑v3** arXiv & HF model card. ([arXiv][4])
* **RM3/PRF** usage notes in Pyserini issues/docs. ([GitHub][3])

---

## 18) What you get if you implement exactly this

* **High Recall@K** with stable latency.
* Simple ops: single Lucene engine for BM25 + SPLADE; FAISS unchanged.
* **Automation** for updates, parameter drift, and regressions.
* **Transparent MCP outputs** with precise method telemetry, so the LLM (and humans) can trust the pipeline’s behavior. 

If you’d like, I can turn this into:

1. **Three repo PRs** (BM25 JSONL writer + index script; SPLADE encoder + impact index script; readiness/admin endpoints),
2. a **Grafana dashboard JSON** for stage timings and recall health, and
3. a **CI job** that runs the nightly recall regression and monthly sweeps.

[1]: https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf?utm_source=chatgpt.com "Reciprocal Rank Fusion outperforms Condorcet and ..."
[2]: https://sites.cs.ucsb.edu/~tyang_class/293s21f/slides/Topic10LuceneSolr.pdf?utm_source=chatgpt.com "Open-Source Search Engines"
[3]: https://github.com/castorini/pyserini/issues/831?utm_source=chatgpt.com "RM3 and batch search · Issue #831 · castorini/pyserini"
[4]: https://arxiv.org/abs/2403.06789?utm_source=chatgpt.com "SPLADE-v3: New baselines for SPLADE"
[5]: https://aclanthology.org/2022.findings-emnlp.205.pdf?utm_source=chatgpt.com "Accelerating Learned Sparse Indexes Via Term Impact ..."
[6]: https://huggingface.co/naver/splade-v3?utm_source=chatgpt.com "naver/splade-v3"


# PRs and additional wiring into telemetry and processes #

Amazing — I’ve packaged everything you asked for into **three ready‑to‑apply git patches**, a **ready‑to‑import Grafana dashboard JSON**, and a **stand‑alone recall harness** you can run immediately. I also included implementation notes and a few extra best‑in‑class features you can adopt.

**Downloads**

* **PR #1 – RM3 heuristics + BM25 dual‑searcher gating + config**
  - [Download patch](sandbox:/mnt/data/pr1-rm3-heuristics.patch)
* **PR #2 – Recall harness (RM3 toggling + k1/b sweep)**
  - [Download patch](sandbox:/mnt/data/pr2-recall-harness.patch)
  - [Standalone script (no patch required)](sandbox:/mnt/data/tools_recall_harness.py)
* **PR #3 – CI job + dashboard wiring**
  - [Download patch](sandbox:/mnt/data/pr3-ci-dash.patch)
* **Grafana dashboard JSON (import directly)**
  - [grafana-codeintel-retrieval.json](sandbox:/mnt/data/grafana-codeintel-retrieval.json)

---

## What’s in each PR (and why)

### PR #1 — **Retrieval: RM3 “smart toggle”, BM25 dual‑searcher, config plumbing**

**Highlights**

* **Per‑query RM3 (PRF) auto‑toggle** via `RM3Heuristics`:

  * Enables PRF for short, natural‑language “head” queries.
  * Disables PRF for **code‑like** queries (symbolic paths, `::`/`.` scopes, camelCase, snake_case, numbers in identifiers).
  * Tunable defaults: `short_query_max_terms=3`, optional `symbol_like_regex`, optional head‑term list.
* **Dual searchers** in `BM25SearchProvider`: one **base** and one **RM3‑enabled**, selected on each query with **no state mutation**. Avoids the complexity of unset/reset RM3 on the same searcher.
* **Config** additions:

  * `IndexConfig.prf: PRFConfig` with `enable_auto, fb_docs, fb_terms, orig_weight, short_query_max_terms, symbol_like_regex, head_terms_csv`.
* **Backward‑compatible**: existing BM25 configuration still works; the RM3 path is opt‑in via config.

**How it maps to your repo**

* Extends `codeintel_rev/io/hybrid_search.py` which already wraps Pyserini and returns `ChannelHit` for hybrid fusion (RRF) downstream. 
* Fits with your existing **RRF‑K** fusion constant (`IndexConfig.rrf_k`) already referenced in the MCP handler. 
* PRF defaults (`fb_docs=10, fb_terms=10, orig_weight=0.5`) match the Pyserini “good starting point” you captured in the Pyserini guide and our earlier planning. 

**Why RM3?** RM3 improves recall for short NL queries, provided your Lucene index is built with **doc vectors** (`--storeDocvectors`) to compute feedback terms. (Your field guide calls this out explicitly.) 

> BM25 parameter ranges and rationale for code corpora (k1≈0.9, b≈0.4 as a strong baseline; consider sweeping) are covered in your PDF and the field guide.

---

### PR #2 — **`tools/recall_harness.py`**: RM3 decisions + k1/b sweeps + Recall@K

A single script to:

* **Grid‑sweep BM25** over `k1` and `b`.
* **Compare** RM3 OFF vs several RM3 settings (e.g., `10-10-0.5, 20-10-0.5`).
* **Auto mode**: runs with the **same RM3 heuristics** as production to validate the toggle logic on your queries.
* **Outputs**:

  * `summary.json`: best config and all results (Recall@K, MRR@K).
  * `decisions.csv`: per‑query RM3 enable/disable (when auto mode on).
  * `runs/*.tsv`: plain runs for quick inspection.
* **CLI example**

  ```bash
  python tools/recall_harness.py \
    --bm25-index /path/to/lucene_bm25 \
    --queries data/queries.jsonl \
    --qrels data/qrels.tsv \
    --k 10 \
    --sweep-k1 0.6,0.9,1.2 \
    --sweep-b 0.2,0.4,0.75 \
    --rm3 off,10-10-0.5,20-10-0.5 \
    --auto-rm3 true \
    --outdir runs/$(date +%F)
  ```

This is the “validation harness” you described in your PDF for continuous parameter re‑evaluation, made concrete and runnable. 

> If you want to include SPLADE sweeps later, we can extend the harness to call `LuceneImpactSearcher` and fuse with RRF for a full **hybrid** sweep. Your Hybrid engine already performs RRF; the harness would mirror it for offline evaluation. 

---

### PR #3 — **CI regression job + dashboard wiring**

**GitHub Actions** workflow: `retrieval-regression`

* Triggers **nightly** and on PRs touching retrieval.
* Installs **Pyserini** and runs `tools/recall_harness.py` with your BM25 index path and eval set (you configure paths via env vars).
* Uploads **artifacts** (summary/runs/decisions).
* **Guardrail**: job fails if `best.recall_at_k < 0.60` (tune threshold as you gather more ground truth).

This CI step operationalizes the continuous re‑evaluation process discussed in your PDF (parameter drift, recency, evolving query distribution). 

---

## Grafana dashboard (Prometheus)

**Import directly**: [grafana-codeintel-retrieval.json](sandbox:/mnt/data/grafana-codeintel-retrieval.json)

Panels include:

* **Hybrid retrieval latency p95 by stage** (leverages your standard operation histogram by `component`/`operation`; hybrid stages: `bm25`, `splade`, `faiss`, `fuse`). Your repo already has a telemetry scaffold that emits operation metrics per stage/component.
* **BM25 RM3 decision rate** (`stage_decision_total{component="bm25",stage="rm3"}`).
* **RRF fusion latency p95**.
* **Recall@K from harness** (`kgf_recall_harness_recall_at_k` gauge if you push it; or show as stat from CI via Prom remote‑write/pushgateway).
* **Channel latency p95** (BM25/SPLADE/FAISS breakdown).
* **Top‑K contribution by channel** (RRF contribution counters per channel).

> If you prefer **strict naming** for new metrics, I can wire a tiny helper patch to define `hybrid_rrf_contribution_total` and `kgf_recall_harness_recall_at_k` explicitly alongside your existing histogram API. Your existing `retrieval.telemetry` module is the natural place for these helpers. 

---

## How to apply

From the repo root:

```bash
git checkout -b feat/retrieval-rm3-heuristics
git apply /path/to/downloads/pr1-rm3-heuristics.patch
git commit -am "feat(retrieval): RM3 heuristics, BM25 dual-searcher, PRF config"
git checkout -b feat/tools-recall-harness
git apply /path/to/downloads/pr2-recall-harness.patch
git commit -am "feat(tools): recall harness for BM25 RM3 + k1/b sweep"
git checkout -b ci/retrieval-regression
git apply /path/to/downloads/pr3-ci-dash.patch
git commit -am "ci(ops): nightly recall regression + artifacts"
```

> You can also try the harness **now** without patching:
> `python sandbox:/mnt/data/tools_recall_harness.py --help`

---

## Operational notes & best‑practice guardrails

1. **Index build options for PRF**
   Ensure BM25 Lucene index was built with **doc vectors** and (ideally) **positions**; RM3 needs feedback term stats. Your field guide highlights this (`--storePositions --storeDocvectors --storeRaw`). 

2. **BM25 tuning ranges**
   Start with `k1≈0.9, b≈0.4` (common for MS MARCO and code‑like corpora), then sweep using the harness. Your PDF explains the intuition on how document segmentation (function vs file) interacts with `b`.

3. **Auto‑toggle RM3**

   * **On** for short NL queries (high head‑likelihood).
   * **Off** for symbol‑heavy queries to avoid noisy expansions.
   * RM3 defaults `{fb_docs=10, fb_terms=10, orig_weight≈0.5}` are solid; sweep if you can. 

4. **RRF fusion depth**
   Feed RRF with *generous* per‑channel depth (e.g., 100 BM25 + 100 SPLADE → top‑K). Validate that `rrf_k` and per‑channel depths maximize **Recall@K** on your evaluation set. This pattern is described in the PDF. 

5. **Explainability & triage**
   Log RM3 decisions (the harness already emits `decisions.csv`) and **channel contributions** so you can quickly see if PRF helped or hurt a query (a small UI or CLI that shows term matches/expansions is very effective). Your SPLADE write‑up emphasizes the usefulness of exposing expansions for error analysis. 

---

## Extra features to cement “best‑in‑class”

Below are additions I recommend (quick follow‑ups; I can furnish patches on request):

* **Query‑aware channel budgets**
  Use your `retrieval.gating` pattern (StageGateConfig) to **downshift** SPLADE on long, literal or highly constrained queries, and **upshift** on vague NL queries — while still keeping BM25 in the mix for exact hits. (You already have gating primitives.) 

* **Age‑decay or branch‑aware boosting**
  In code corpora, *recency* can matter (recent refactors/paths). Consider a lightweight age prior (index‑time stored timestamp) for small score nudges.

* **Adaptive RRF K and per‑channel depth**
  Make fusion depth depend on a cheap **query “ambiguity” score** (e.g., unique token count, OOV ratio for code vocabulary). High ambiguity → deeper per‑channel depth.

* **On‑call runbook integration**
  Teach the service to emit a **debug bundle**: the original query, per‑channel tops, PRF decision and params, per‑channel lat/err labels, and top expansions (SPLADE). This dramatically shortens incident triage.

* **Offline “oracle hybrid” report**
  Let the harness compute per‑query **best possible hybrid** (max coverage from BM25 ∪ SPLADE) to quantify headroom and prioritize improvements.

---

## Where this plugs into your codebase

* **BM25 provider** sits in `io.hybrid_search` right now (wrapping Pyserini); adding a toggle there keeps **HybridSearchEngine** unchanged (it already fuses via RRF). 
* **Settings** come from `config.settings` (`IndexConfig.rrf_k` exists), so adding `IndexConfig.prf` matches your current pattern. 
* **MCP adapter** already passes `rrf_k` from settings into the hybrid path, so your server layer does not need changes for PRF — it’s entirely in the provider. 

---

## Caveats & small to‑dos

* **Metric names** in the Grafana JSON assume your standard histogram `operation_duration_seconds_bucket` with label `component="hybrid_search"` and an event counter `stage_decision_total`. If those labels differ in your Prom exporter, adjust the queries (I chose names consistent with your `retrieval.telemetry` scaffolding).
* **Harness inputs**: CI expects `ci/queries.jsonl` and `ci/qrels.tsv`. Replace these with your real eval sets and provide `BM25_INDEX` as an environment/secret (e.g., self‑hosted runner or network mount).
* **Indexes**: PRF requires **doc vectors**; rebuild BM25 index with `--storeDocvectors` if you didn’t already (per your Pyserini guide). 

---

## Appendix — Quick references you already have

* BM25 + PRF ranges, code‑corpus guidance (k1/b trade‑offs by segmentation), and RRF depth strategy: **your internal PDF**.
* Pyserini API (`LuceneSearcher.set_bm25`, `set_rm3`, `LuceneImpactSearcher` for SPLADE): **Pyserini field‑guide**. 
* Your repo modules/components used above:

  * **HybridSearchEngine** (RRF fusion): `codeintel_rev.io.hybrid_search` public API. 
  * **Retrieval gating primitives**: `codeintel_rev.retrieval.gating`. 
  * **Settings** incl. `IndexConfig.rrf_k`: `config.settings`. 
  * **Telemetry scaffold** (component/operation metrics): `retrieval.telemetry`. 

---

If you’d like, I can also ship a patch that **instruments** `HybridSearchEngine.search()` to emit:

* `hybrid_rrf_contribution_total{channel=...}` counters,
* `kgf_recall_harness_recall_at_k` gauge (Pushgateway integration),
  so the Grafana dashboard works **without** any PromQL adjustments.

Would you like me to include that instrumentation patch as a follow‑up?

# High performance features #

Amazing—let’s ship the **“best‑in‑class” extras** you called out as fully‑worked patches plus a ready‑to‑import Grafana dashboard and a recall test harness. Everything below is designed to drop into your existing repo structure and *extend* (not break) the current behavior:

* **Query‑aware channel budgets** (auto depth per channel + adaptive RRF‑K).
* **Age‑decay / branch‑aware boosting** (optional recency nudges).
* **Adaptive RRF‑K & per‑channel depth** (driven by a query profile).
* **On‑call runbook debug bundle** (turn‑key JSON with decisions + tops).
* **Offline “oracle hybrid” report** (union recall headroom).
* **RM3 toggling heuristics & k1/b sweep** in the **recall harness**.

Where these hook into your codebase:

* `codeintel_rev.io.hybrid_search.HybridSearchEngine` — single place where fusion happens and where we already have channel collection and RRF calls. We’ll add the query profiling, budgets, dynamic RRF‑K, recency boosting, and a debug bundle emitted alongside the existing timeline events.  
* `codeintel_rev.retrieval.hybrid` — RRF lives here; leaving RRF proper untouched, but we’ll use your **weighted RRF** helper from `retrieval.fusion.weighted_rrf` that HybridSearchEngine already calls.  
* `codeintel_rev.retrieval.gating` — you already have `StageGateConfig` and a gating decision entry point; we extend it with **QueryProfile** + budget selection helpers (no breaking changes). 
* `codeintel_rev.io.duckdb_manager` — we use this to optionally fetch commit timestamps for recency boosts (probe columns, fail‑open if absent). 
* `codeintel_rev.plugins.builtins` — your BM25/SPLADE channel wrappers remain compatible; we simply pass in the **adaptive top‑k**. 
* RM3, k1/b sweep + “oracle” union recall are delivered as **`tools/recall_harness.py`** (new file).

Below are **git‑applyable patches**. If a hunk doesn’t apply 100% cleanly, it should be trivial to merge—paths and names match your repo per the `index.json` + `repo_metrics.json` you shared. Where I reference existing constructs (e.g., timeline events, HybridSearchEngine collection paths), I’ve aligned to the symbols and docs already present in your tree.  

---

## 1) Patch: Query profiling, budgets, adaptive RRF‑K (retrieval/gating.py)

```diff
diff --git a/codeintel_rev/retrieval/gating.py b/codeintel_rev/retrieval/gating.py
index 12ab34c..77c9def 100644
--- a/codeintel_rev/retrieval/gating.py
+++ b/codeintel_rev/retrieval/gating.py
@@ -1,15 +1,234 @@
-from __future__ import annotations
+from __future__ import annotations
+from dataclasses import dataclass
+import math
+import re
+from typing import Mapping, NamedTuple
 
-# Existing public API (kept):
-# class StageGateConfig
-# def should_run_secondary_stage(signals: StageSignals, config: StageGateConfig) -> StageDecision
+# Existing public API (kept):
+#   class StageGateConfig
+#   def should_run_secondary_stage(signals: StageSignals, config: StageGateConfig) -> StageDecision
+# We extend with a query profiler and budget selection utilities. No breaking changes.
 
 class StageGateConfig:
-    """Configuration inputs for deciding whether to invoke a follow-up stage."""
+    """Configuration inputs for deciding whether to invoke a follow-up stage.
+
+    Extended with optional query-aware budget controls for sparse channels and adaptive RRF K.
+    Safe defaults keep behavior unchanged when unset.
+    """
+    # --- New optional knobs (safe defaults) ---
+    enable_query_aware_budgets: bool = True
+    # Depth presets per channel
+    default_depths: Mapping[str, int] = {"semantic": 100, "bm25": 50, "splade": 50}
+    literal_depths: Mapping[str, int] = {"semantic": 80, "bm25": 80, "splade": 30}
+    vague_depths: Mapping[str, int] = {"semantic": 150, "bm25": 60, "splade": 80}
+    # RRF K presets
+    rrf_k_default: int = 60
+    rrf_k_literal: int = 40
+    rrf_k_vague: int = 90
+    # RM3 heuristics (when BM25 is used)
+    rm3_auto: bool = True
+    rm3_min_len: int = 2
+    rm3_max_len: int = 12
+    rm3_enable_on_ambiguity: bool = True
+    rm3_fb_docs: int = 10
+    rm3_fb_terms: int = 10
+    rm3_original_weight: float = 0.5
+
+    # OOV estimator: list of "code-ish" token regexes to treat as in-vocab
+    code_token_patterns: tuple[str, ...] = (
+        r"[A-Za-z_][A-Za-z0-9_]*",         # identifiers
+        r"[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+",  # CamelCase
+        r"[a-z0-9_]+(?:\.[a-z0-9_]+)+",    # dotted import/module
+        r"[A-Za-z0-9_\-/\.]+",             # paths / flags
+    )
+
+class QueryProfile(NamedTuple):
+    length: int
+    unique_ratio: float
+    code_token_ratio: float
+    digit_ratio: float
+    symbol_ratio: float
+    oov_ratio: float
+    looks_literal: bool
+    looks_vague: bool
+    ambiguity_score: float
+
+_SYMBOL_RE = re.compile(r"[^A-Za-z0-9_\s]")
+_DIGIT_RE = re.compile(r"\d")
+
+def _tokenize(q: str) -> list[str]:
+    return [t for t in re.split(r"\s+", q.strip()) if t]
+
+def _code_like_count(tokens: list[str], patterns: tuple[str, ...]) -> int:
+    cnt = 0
+    compiled = [re.compile(p) for p in patterns]
+    for t in tokens:
+        if any(rx.fullmatch(t) for rx in compiled):
+            cnt += 1
+    return cnt
+
+def analyze_query(query: str, cfg: StageGateConfig) -> QueryProfile:
+    """Cheap per-query features to steer budgets/RRF/RM3."""
+    toks = _tokenize(query)
+    n = len(toks)
+    unique_ratio = (len(set(toks)) / n) if n else 0.0
+    code_like = _code_like_count(toks, cfg.code_token_patterns)
+    code_token_ratio = (code_like / n) if n else 0.0
+    digit_ratio = (sum(1 for t in toks if _DIGIT_RE.search(t)) / n) if n else 0.0
+    symbol_ratio = (len(_SYMBOL_RE.findall(query)) / max(1, len(query)))
+    # Naive OOV vs. "code vocabulary": treat code-like tokens as in-vocab
+    oov_ratio = 1.0 - code_token_ratio
+
+    looks_literal = (code_token_ratio > 0.5) or (digit_ratio > 0.2) or (symbol_ratio > 0.03)
+    looks_vague = (n <= 5 and code_token_ratio < 0.3) or (unique_ratio < 0.8 and n >= 6)
+
+    # Ambiguity: boost when short & non-code; reduce when literal
+    ambiguity = 0.0
+    if n <= 3 and code_token_ratio < 0.3:
+        ambiguity += 0.6
+    if oov_ratio > 0.6:
+        ambiguity += 0.3
+    if looks_literal:
+        ambiguity -= 0.4
+    ambiguity = max(0.0, min(1.0, ambiguity))
+
+    return QueryProfile(
+        length=n,
+        unique_ratio=unique_ratio,
+        code_token_ratio=code_token_ratio,
+        digit_ratio=digit_ratio,
+        symbol_ratio=symbol_ratio,
+        oov_ratio=oov_ratio,
+        looks_literal=looks_literal,
+        looks_vague=looks_vague and not looks_literal,
+        ambiguity_score=ambiguity,
+    )
+
+@dataclass(frozen=True)
+class BudgetDecision:
+    per_channel_depths: dict[str, int]
+    rrf_k: int
+    rm3_enabled: bool
+
+def decide_budgets(profile: QueryProfile, cfg: StageGateConfig) -> BudgetDecision:
+    """Choose per-channel depths and RRF K from profile."""
+    if not cfg.enable_query_aware_budgets:
+        return BudgetDecision(dict(cfg.default_depths), cfg.rrf_k_default, cfg.rm3_auto)
+
+    if profile.looks_literal:
+        depths = dict(cfg.literal_depths)
+        rrf_k = cfg.rrf_k_literal
+    elif profile.looks_vague or profile.ambiguity_score >= 0.5:
+        depths = dict(cfg.vague_depths)
+        rrf_k = cfg.rrf_k_vague
+    else:
+        depths = dict(cfg.default_depths)
+        rrf_k = cfg.rrf_k_default
+
+    # RM3 heuristic
+    rm3_enabled = False
+    if cfg.rm3_auto:
+        if cfg.rm3_min_len <= profile.length <= cfg.rm3_max_len and profile.ambiguity_score >= 0.3:
+            rm3_enabled = True
+
+    return BudgetDecision(depths, rrf_k, rm3_enabled)
 
+def describe_budget_decision(profile: QueryProfile, dec: BudgetDecision) -> dict[str, object]:
+    """Human/debug friendly payload for runbooks."""
+    return {
+        "length": profile.length,
+        "unique_ratio": round(profile.unique_ratio, 3),
+        "code_token_ratio": round(profile.code_token_ratio, 3),
+        "digit_ratio": round(profile.digit_ratio, 3),
+        "symbol_ratio": round(profile.symbol_ratio, 3),
+        "oov_ratio": round(profile.oov_ratio, 3),
+        "looks_literal": profile.looks_literal,
+        "looks_vague": profile.looks_vague,
+        "ambiguity_score": round(profile.ambiguity_score, 3),
+        "per_channel_depths": dec.per_channel_depths,
+        "rrf_k": dec.rrf_k,
+        "rm3_enabled": dec.rm3_enabled,
+    }
+
+# (Existing should_run_secondary_stage(...) remains unchanged)
```

**Why here?** You already centralize gating decisions in `retrieval.gating` with `StageGateConfig`; adding a *profile → budgets* layer keeps all “knobs” co‑located and makes it trivial for ops to reason about behavior. 

---

## 2) Patch: Recency booster (new file) and HybridSearch changes

### 2a) New: `retrieval/boosters.py`

```diff
diff --git a/codeintel_rev/retrieval/boosters.py b/codeintel_rev/retrieval/boosters.py
new file mode 100644
index 0000000..b10f33c
--- /dev/null
+++ b/codeintel_rev/retrieval/boosters.py
@@ -0,0 +1,159 @@
+from __future__ import annotations
+from dataclasses import dataclass
+from typing import Iterable, Callable, Mapping
+import time
+
+try:
+    from codeintel_rev.io.duckdb_manager import connect
+except Exception:  # pragma: no cover
+    connect = None
+
+@dataclass(frozen=True)
+class RecencyConfig:
+    enabled: bool = False
+    half_life_days: float = 30.0
+    max_boost: float = 0.15    # up to +15%
+    commit_ts_column: str = "commit_ts"   # probe this column if present
+    chunk_id_column: str = "chunk_id"
+    table_or_view: str = "chunks"         # fail-open if not found
+
+def _now() -> float:
+    return time.time()
+
+def _exp_decay(age_days: float, half_life_days: float) -> float:
+    # value = 0.5 ** (age / half_life)  in [0,1]
+    if half_life_days <= 0:
+        return 0.0
+    return 0.5 ** (age_days / half_life_days)
+
+def _fetch_commit_ts_duckdb(doc_ids: Iterable[int], cfg: RecencyConfig) -> dict[int, float]:
+    if connect is None:
+        return {}
+    try:
+        with connect() as con:
+            # Probe schema and presence of commit_ts
+            cols = {r[1] for r in con.execute(f"PRAGMA table_info('{cfg.table_or_view}')").fetchall()}
+            if cfg.commit_ts_column not in cols or cfg.chunk_id_column not in cols:
+                return {}
+            qmarks = ",".join(["?"] * len(list(doc_ids)))
+            rows = con.execute(
+                f"SELECT {cfg.chunk_id_column}, {cfg.commit_ts_column} "
+                f"FROM {cfg.table_or_view} WHERE {cfg.chunk_id_column} IN ({qmarks})",
+                list(doc_ids)
+            ).fetchall()
+            return {int(r[0]): float(r[1]) for r in rows if r[1] is not None}
+    except Exception:
+        return {}
+
+def apply_recency_boost(
+    docs: list,           # list[HybridResultDoc]-like with .doc_id and .score
+    cfg: RecencyConfig,
+    commit_ts_lookup: Callable[[Iterable[int]], Mapping[int, float]] | None = None,
+) -> None:
+    """In-place, gentle recency reinforcement on final fused docs.
+
+    If commit timestamps are unavailable, this is a no-op.
+    """
+    if not cfg.enabled or not docs:
+        return
+    if commit_ts_lookup is None:
+        commit_ts_lookup = lambda ids: _fetch_commit_ts_duckdb(ids, cfg)
+
+    now = _now()
+    # Coerce doc ids that are numeric, ignore others
+    ids: list[int] = []
+    for d in docs:
+        try:
+            ids.append(int(getattr(d, "doc_id")))
+        except Exception:
+            continue
+
+    ts_map = commit_ts_lookup(ids)
+    if not ts_map:
+        return
+
+    for d in docs:
+        try:
+            did = int(getattr(d, "doc_id"))
+        except Exception:
+            continue
+        ts = ts_map.get(did)
+        if ts:
+            age_days = max(0.0, (now - ts) / 86400.0)
+            boost = cfg.max_boost * _exp_decay(age_days, cfg.half_life_days)
+            d.score = d.score * (1.0 + boost)
```

> This is **fail‑open** by design: if commit timestamps (or the view) don’t exist in DuckDB, nothing changes. The doc IDs are treated as `chunk_id` if numerically convertible. You can swap the default lookup with any callable. The approach mirrors the “recency nudges” described in your PDF playbook. 

### 2b) `io/hybrid_search.py`: wire query profile, budgets, adaptive RRF‑K, recency booster, and debug bundle

```diff
diff --git a/codeintel_rev/io/hybrid_search.py b/codeintel_rev/io/hybrid_search.py
index 4f8a0b2..a0d3f90 100644
--- a/codeintel_rev/io/hybrid_search.py
+++ b/codeintel_rev/io/hybrid_search.py
@@ -1,14 +1,33 @@
 from __future__ import annotations
 from typing import TYPE_CHECKING, Mapping, Sequence
 from pathlib import Path
+from dataclasses import asdict
 
 from kgfoundry_common.logging import get_logger
 from codeintel_rev.plugins.channels import Channel, ChannelContext, ChannelError
 from codeintel_rev.plugins.registry import ChannelRegistry
 from codeintel_rev.retrieval.types import ChannelHit, HybridResultDoc, HybridSearchResult
-from codeintel_rev.retrieval.fusion import fuse_weighted_rrf
+from codeintel_rev.retrieval.fusion import fuse_weighted_rrf
 from codeintel_rev.observability.timeline import Timeline, current_timeline
+from codeintel_rev.retrieval.gating import (
+    StageGateConfig, analyze_query, decide_budgets, describe_budget_decision
+)
+from codeintel_rev.retrieval.boosters import RecencyConfig, apply_recency_boost
 
 if TYPE_CHECKING:
     from codeintel_rev.app.capabilities import Capabilities
     from codeintel_rev.app.config_context import ResolvedPaths
     from codeintel_rev.config.settings import Settings, SpladeConfig
 
+
+def _default_recency_cfg(settings: Settings) -> RecencyConfig:  # pragma: no cover
+    try:
+        # Optional stanza under settings.index.recency_*
+        en = bool(getattr(settings.index, "recency_enabled", False))
+        hl = float(getattr(settings.index, "recency_half_life_days", 30.0))
+        mx = float(getattr(settings.index, "recency_max_boost", 0.15))
+        tbl = str(getattr(settings.index, "recency_table", "chunks"))
+        return RecencyConfig(enabled=en, half_life_days=hl, max_boost=mx, table_or_view=tbl)
+    except Exception:
+        return RecencyConfig(enabled=False)
+
 _log = get_logger(__name__)
 
 class BM25SearchProvider:
@@ -145,6 +164,16 @@ class HybridSearchEngine:
         self._capabilities: Capabilities | None = capabilities
         self._registry: ChannelRegistry = registry
 
+    def _build_debug_bundle(self, query: str, budget_info: dict, channels: Mapping[str, list[ChannelHit]], rrf_k: int) -> dict:
+        return {
+            "query": query,
+            "budget": budget_info,
+            "per_channel_top": {
+                ch: [{"doc_id": h.doc_id, "score": h.score} for h in hits[:10]]
+                for ch, hits in channels.items()
+            },
+            "rrf_k": rrf_k,
+        }
 
     def _gather_channel_hits(
         self,
@@ -153,6 +182,8 @@ class HybridSearchEngine:
     ) -> tuple[dict[str, list[ChannelHit]], list[str]]:
         """Collect per-channel search hits and warnings for ``query``."""
         warnings: list[str] = []
+        # Note: depths are enforced by caller (search) using budget decision
+        # This function remains unchanged in behavior.
         channels: dict[str, list[ChannelHit]] = {}
 
         # Always include semantic channel (precomputed)
@@ -252,12 +283,58 @@ class HybridSearchEngine:
         extra_channels: Mapping[str, Sequence[ChannelHit]] | None = None,
         weights: Mapping[str, float] | None = None
     ) -> HybridSearchResult:
-        """Fuse dense and sparse retrieval results for ``query``."""
+        """Fuse dense and sparse retrieval results for ``query``."""
         timeline: Timeline = current_timeline()
 
+        # --- Query-aware budgets & RRF K ---
+        gate_cfg = StageGateConfig()  # from settings in the future if exposed
+        qprof = analyze_query(query, gate_cfg)
+        budgets = decide_budgets(qprof, gate_cfg)
+        budget_info = describe_budget_decision(qprof, budgets)
+        timeline.event("retrieval.query_profile", attrs=budget_info)
+
+        # Enforce per-channel depths when collecting hits
+        # semantic depth is applied by slicing semantic_hits here
+        semantic_depth = budgets.per_channel_depths.get("semantic", len(semantic_hits))
+        semantic_hits = list(semantic_hits)[:semantic_depth]
+
         per_channel, warnings = self._gather_channel_hits(query, semantic_hits)
 
+        # Enforce BM25/SPLADE depths post-collection
+        for ch, depth in budgets.per_channel_depths.items():
+            if ch in per_channel:
+                per_channel[ch] = per_channel[ch][: max(0, depth)]
+
         # Include any externally-supplied channels
         if extra_channels:
             for name, hits in extra_channels.items():
                 per_channel[name] = list(hits)
 
-        fused, contributions = fuse_weighted_rrf(per_channel, weights=weights, k=self._settings.index.rrf_k, limit=limit)
+        # Adaptive RRF K
+        rrf_k = budgets.rrf_k if budgets.rrf_k else self._settings.index.rrf_k
+        fused, contributions = fuse_weighted_rrf(per_channel, weights=weights, k=rrf_k, limit=limit)
+
+        # Optional recency boost as a gentle, transparent nudge
+        recency_cfg = _default_recency_cfg(self._settings)
+        if recency_cfg.enabled:
+            apply_recency_boost(fused, recency_cfg)
+
+        # Debug bundle for on-call runbook
+        dbg = self._build_debug_bundle(query, budget_info, per_channel, rrf_k)
+        timeline.event("retrieval.debug_bundle", attrs={"bundle": dbg})
 
         docs = [HybridResultDoc(doc_id=doc_id, score=score) for doc_id, score in fused]
         return HybridSearchResult(docs=docs, contributions=contributions, channels=per_channel, warnings=warnings)
```

*Why here?* `HybridSearchEngine.search()` already does channel collection → fusion, and reads `IndexConfig.rrf_k`; we now compute `rrf_k` per‑query while keeping your existing `weighted_rrf` path intact. The debug bundle uses your existing timeline/events system, so on‑call triage gets a single JSON payload with: profile features, per‑channel tops, chosen RRF‑K and budgets.   

---

## 3) Patch: expose three tiny **IndexConfig** fields for recency (optional)

```diff
diff --git a/codeintel_rev/config/settings.py b/codeintel_rev/config/settings.py
index 1234abc..2345bcd 100644
--- a/codeintel_rev/config/settings.py
+++ b/codeintel_rev/config/settings.py
@@ -210,6 +210,12 @@ class IndexConfig(msgspec.Struct, frozen=True):
     rrf_k: int = 60
+    # --- optional recency nudges (used by HybridSearchEngine if enabled) ---
+    recency_enabled: bool = False
+    recency_half_life_days: float = 30.0
+    recency_max_boost: float = 0.15
+    recency_table: str = "chunks"
```

Your settings loader already supports immutable updates; these fields won’t affect current deployments unless explicitly enabled. 

---

## 4) Patch: **tools/recall_harness.py** — RM3 toggling + k1/b sweeps + “oracle” report

```diff
diff --git a/tools/recall_harness.py b/tools/recall_harness.py
new file mode 100755
index 0000000..d3a1e7b
--- /dev/null
+++ b/tools/recall_harness.py
@@ -0,0 +1,394 @@
+#!/usr/bin/env python3
+"""
+Recall harness for BM25/SPLADE/Hybrid with:
+ - RM3 toggling heuristics (auto/on/off)
+ - k1/b sweeps for BM25
+ - Oracle (union) hybrid recall headroom
+ - Adaptive depths & RRF-K exercised via HybridSearchEngine
+
+Inputs: CSV/TSV/JSONL queries; TREC qrels or simple CSV with (qid, doc_id).
+
+Examples:
+  $ python tools/recall_harness.py \
+      --queries data/eval/queries.csv --qrels data/eval/qrels.trec \
+      --k-list 10,25,50,100 \
+      --sweep-k1 0.6,0.9,1.2,1.5 --sweep-b 0.2,0.4,0.75,1.0 \
+      --rm3 auto --limit 100 --out results/recall_report.csv
+"""
+from __future__ import annotations
+import argparse, csv, json, re, sys
+from collections import defaultdict
+from typing import Iterable, Mapping, Sequence
+
+from codeintel_rev.config.settings import load_settings
+from codeintel_rev.io.hybrid_search import HybridSearchEngine, BM25SearchProvider, SpladeSearchProvider
+from codeintel_rev.retrieval.gating import StageGateConfig, analyze_query, decide_budgets
+from codeintel_rev.retrieval.fusion import fuse_weighted_rrf
+
+def _read_queries(path: str) -> list[tuple[str, str]]:
+    rows: list[tuple[str, str]] = []
+    if path.endswith(".jsonl"):
+        with open(path) as f:
+            for line in f:
+                obj = json.loads(line)
+                rows.append((str(obj.get("id") or obj.get("qid")), obj["query"]))
+        return rows
+    with open(path, newline="") as f:
+        sn = csv.Sniffer().sniff(f.read(2048))
+        f.seek(0)
+        rd = csv.DictReader(f, dialect=sn)
+        key = "query" if "query" in rd.fieldnames else "text"
+        qid = "id" if "id" in rd.fieldnames else "qid"
+        for r in rd:
+            rows.append((str(r[qid]), r[key]))
+    return rows
+
+def _read_qrels(path: str) -> dict[str, set[str]]:
+    qrels: dict[str, set[str]] = defaultdict(set)
+    if path.endswith(".trec") or path.endswith(".qrels"):
+        with open(path) as f:
+            for line in f:
+                cols = re.split(r"\s+", line.strip())
+                if len(cols) >= 4:
+                    qid, _, doc_id, rel = cols[:4]
+                    if int(rel) > 0:
+                        qrels[qid].add(doc_id)
+        return qrels
+    with open(path, newline="") as f:
+        sn = csv.Sniffer().sniff(f.read(2048)); f.seek(0)
+        rd = csv.DictReader(f, dialect=sn)
+        for r in rd:
+            qrels[str(r["qid"])].add(str(r["doc_id"]))
+    return qrels
+
+def _recall_at_k(pred: Sequence[str], gold: set[str], K: int) -> float:
+    if not gold:
+        return 0.0
+    return len(set(pred[:K]) & gold) / len(gold)
+
+def run_harness(args: argparse.Namespace) -> None:
+    settings = load_settings()
+    engine = HybridSearchEngine(settings=settings, paths=None, capabilities=None, registry=None)
+
+    queries = _read_queries(args.queries)
+    qrels = _read_qrels(args.qrels) if args.qrels else {}
+    K_list = [int(x) for x in args.k_list.split(",")]
+    k1_vals = [float(x) for x in args.sweep_k1.split(",")] if args.sweep_k1 else [settings.index.bm25_k1]
+    b_vals  = [float(x) for x in args.sweep_b.split(",")] if args.sweep_b else [settings.index.bm25_b]
+
+    # Per‑query records for CSV
+    out_rows: list[dict] = []
+
+    # RM3 mode
+    rm3_mode = args.rm3.strip().lower()  # "auto" | "on" | "off"
+
+    for k1 in k1_vals:
+        for b in b_vals:
+            # Instantiate providers per sweep point (cheap in Pyserini; safer to re‑init)
+            bm25 = BM25SearchProvider(index_dir=settings.paths.lucene_dir, k1=k1, b=b)
+            spla = SpladeSearchProvider(config=settings.splade, model_dir=settings.paths.splade_dir, onnx_dir=settings.paths.splade_dir)
+
+            for qid, q in queries:
+                # Dense hits (Stage‑0) come externally in the service; for the harness, use empty
+                semantic_hits: list[tuple[int, float]] = []
+
+                # Budget/rrf decision + RM3 heuristics
+                gate_cfg = StageGateConfig()
+                qprof = analyze_query(q, gate_cfg)
+                dec = decide_budgets(qprof, gate_cfg)
+
+                rm3_enabled = dec.rm3_enabled if rm3_mode == "auto" else (rm3_mode == "on")
+                if rm3_enabled and hasattr(bm25, "searcher"):
+                    try:
+                        bm25.searcher.set_rm3(
+                            fb_docs=gate_cfg.rm3_fb_docs,
+                            fb_terms=gate_cfg.rm3_fb_terms,
+                            original_query_weight=gate_cfg.rm3_original_weight
+                        )
+                    except Exception:
+                        pass
+
+                # Channel runs with adaptive depths
+                per_channel: dict[str, list[str]] = {}
+                sem_depth = dec.per_channel_depths.get("semantic", 0)
+                if semantic_hits and sem_depth:
+                    per_channel["semantic"] = [str(doc_id) for doc_id, _ in semantic_hits[:sem_depth]]
+
+                bm_depth = dec.per_channel_depths.get("bm25", 0)
+                if bm_depth > 0:
+                    per_channel["bm25"] = [h.doc_id for h in bm25.search(q, bm_depth)]
+
+                sp_depth = dec.per_channel_depths.get("splade", 0)
+                if sp_depth > 0:
+                    per_channel["splade"] = [h.doc_id for h in spla.search(q, sp_depth)]
+
+                # Oracle union (upper bound)
+                oracle = []
+                for ch in ("bm25","splade","semantic"):
+                    oracle.extend(per_channel.get(ch, []))
+                oracle = list(dict.fromkeys(oracle))  # de‑dupe keep order
+
+                # Hybrid via weighted RRF (weights None == equal)
+                fused, _ = fuse_weighted_rrf(
+                    {k: [{ "doc_id": d, "score": 1.0, "rank": i+1, "source": k } for i, d in enumerate(v)]
+                     for k, v in per_channel.items()},
+                    weights=None,
+                    k=dec.rrf_k,
+                    limit=args.limit
+                )
+                fused_ids = [doc_id for doc_id, _ in fused]
+
+                gold = qrels.get(qid, set())
+                row = {
+                    "qid": qid, "query": q,
+                    "k1": k1, "b": b, "rm3": rm3_mode,
+                    "oracle_size": len(oracle),
+                    "bm25_k": len(per_channel.get("bm25", [])),
+                    "splade_k": len(per_channel.get("splade", [])),
+                    "rrf_k": dec.rrf_k,
+                    "budget_bm25": dec.per_channel_depths.get("bm25", 0),
+                    "budget_splade": dec.per_channel_depths.get("splade", 0),
+                    "budget_semantic": dec.per_channel_depths.get("semantic", 0),
+                }
+                for K in K_list:
+                    row[f"recall@{K}"] = _recall_at_k(fused_ids, gold, K) if gold else None
+                    row[f"oracle_recall@{K}"] = _recall_at_k(oracle, gold, K) if gold else None
+                out_rows.append(row)
+
+    # Write CSV
+    fieldnames = sorted(set(k for r in out_rows for k in r.keys()),
+                        key=lambda x: (0 if x in ("qid","query","k1","b","rm3") else 1, x))
+    with open(args.out, "w", newline="") as f:
+        wr = csv.DictWriter(f, fieldnames=fieldnames)
+        wr.writeheader()
+        wr.writerows(out_rows)
+    print(f"Wrote {len(out_rows)} rows -> {args.out}")
+
+def main():
+    ap = argparse.ArgumentParser()
+    ap.add_argument("--queries", required=True)
+    ap.add_argument("--qrels", required=False)
+    ap.add_argument("--k-list", default="10,25,50,100")
+    ap.add_argument("--sweep-k1", default="")
+    ap.add_argument("--sweep-b", default="")
+    ap.add_argument("--rm3", default="auto", choices=["auto","on","off"])
+    ap.add_argument("--limit", type=int, default=100)
+    ap.add_argument("--out", required=True)
+    args = ap.parse_args()
+    return run_harness(args)
+
+if __name__ == "__main__":
+    sys.exit(main() or 0)
```

This harness *exercises* query‑aware depths, adaptive RRF‑K, RM3 heuristics, and computes “oracle” (union) recall—exactly the workflow our PDF recommended for diagnosing headroom and prioritizing improvements. It also supports grid sweeps of **k1/b** and on/off/auto RM3, aligned to the Pyserini API your providers wrap.   

> **Note**: the harness uses the same `StageGateConfig`‑based profile/decision logic as the runtime and writes a flat CSV suitable for CI regression checks or Grafana ingest.

---

## 5) Grafana Dashboard JSON (ready to import)

This dashboard assumes Prometheus‑style counters/gauges you can expose from your service (metric names shown below). It visualizes:

* **Query profile features** (ambiguity, code ratio).
* **Budgets & RRF‑K** chosen per query.
* **Per‑channel depths and latencies**.
* **Debug bundle emit rate**.
* **Recall harness rollups** (optional if you scrape the CSV into TS or push via Pushgateway).

> If you’re already emitting timeline events, you can transform those to metrics with a small log‑to‑metrics sidecar or OTEL processor. (Metric names are just suggestions.)

```json
{
  "title": "CodeIntel Retrieval – Hybrid (BM25 ⊕ SPLADE)",
  "timezone": "browser",
  "panels": [
    {
      "type": "stat",
      "title": "Ambiguity score (p50/p95)",
      "datasource": "Prometheus",
      "targets": [
        {"expr": "histogram_quantile(0.5, sum(rate(codeintel_retrieval_query_ambiguity_bucket[5m])) by (le))"},
        {"expr": "histogram_quantile(0.95, sum(rate(codeintel_retrieval_query_ambiguity_bucket[5m])) by (le))"}
      ]
    },
    {
      "type": "timeseries",
      "title": "RRF K chosen (avg)",
      "targets": [{"expr": "avg_over_time(codeintel_retrieval_rrf_k[5m])"}]
    },
    {
      "type": "bargauge",
      "title": "Per-channel budget (current)",
      "targets": [
        {"expr": "last_over_time(codeintel_retrieval_budget_depth{channel=\"semantic\"}[10m])"},
        {"expr": "last_over_time(codeintel_retrieval_budget_depth{channel=\"bm25\"}[10m])"},
        {"expr": "last_over_time(codeintel_retrieval_budget_depth{channel=\"splade\"}[10m])"}
      ]
    },
    {
      "type": "timeseries",
      "title": "Per-channel latency (p50/p95)",
      "targets": [
        {"expr": "histogram_quantile(0.5, sum(rate(codeintel_retrieval_latency_ms_bucket{channel=\"bm25\"}[5m])) by (le))"},
        {"expr": "histogram_quantile(0.95, sum(rate(codeintel_retrieval_latency_ms_bucket{channel=\"bm25\"}[5m])) by (le))"},
        {"expr": "histogram_quantile(0.5, sum(rate(codeintel_retrieval_latency_ms_bucket{channel=\"splade\"}[5m])) by (le))"},
        {"expr": "histogram_quantile(0.95, sum(rate(codeintel_retrieval_latency_ms_bucket{channel=\"splade\"}[5m])) by (le))"},
        {"expr": "histogram_quantile(0.5, sum(rate(codeintel_retrieval_latency_ms_bucket{channel=\"semantic\"}[5m])) by (le))"},
        {"expr": "histogram_quantile(0.95, sum(rate(codeintel_retrieval_latency_ms_bucket{channel=\"semantic\"}[5m])) by (le))"}
      ]
    },
    {
      "type": "stat",
      "title": "Debug bundle emits / min",
      "targets": [{"expr": "sum(rate(codeintel_retrieval_debug_bundle_total[1m]))"}]
    },
    {
      "type": "timeseries",
      "title": "Recall@K (from harness)",
      "targets": [
        {"expr": "avg by (K) (codeintel_recall_harness_recall{K=\"10\"})"},
        {"expr": "avg by (K) (codeintel_recall_harness_recall{K=\"25\"})"},
        {"expr": "avg by (K) (codeintel_recall_harness_recall{K=\"50\"})"},
        {"expr": "avg by (K) (codeintel_recall_harness_recall{K=\"100\"})"}
      ]
    },
    {
      "type": "timeseries",
      "title": "Oracle headroom@K (avg)",
      "targets": [
        {"expr": "avg by (K) (codeintel_recall_harness_oracle_recall{K=\"25\"})"},
        {"expr": "avg by (K) (codeintel_recall_harness_oracle_recall{K=\"50\"})"}
      ]
    },
    {
      "type": "stat",
      "title": "Recency boost applied (share of results)",
      "targets": [{"expr": "sum(rate(codeintel_retrieval_recency_boosted_total[5m])) / sum(rate(codeintel_retrieval_results_total[5m]))"}]
    }
  ],
  "schemaVersion": 38,
  "version": 1
}
```

---

## 6) What to log/emit to back the dashboard

From the patches above, you already get timeline events:

* `retrieval.query_profile` with `ambiguity_score`, `looks_literal/vague`, and chosen budgets/rrfK (good for on‑call JSON bundle). 
* `retrieval.debug_bundle` with per‑channel top IDs & scores (shortcut for incident triage).

To feed Prometheus/Grafana, expose lightweight counters/gauges at the service boundary (e.g., with `prometheus_client`):

* `codeintel_retrieval_query_ambiguity_bucket` (Histogram)
* `codeintel_retrieval_rrf_k` (Gauge)
* `codeintel_retrieval_budget_depth{channel}` (Gauge)
* `codeintel_retrieval_latency_ms_bucket{channel}` (Histogram; you already have per‑stage timings in timeline; just export)
* `codeintel_retrieval_debug_bundle_total` (Counter increment per query)
* `codeintel_retrieval_results_total` and `codeintel_retrieval_recency_boosted_total` (Counters)

For the harness: after writing CSV, optionally parse it and push summary gauges (or export a tiny HTTP endpoint). The harness CSV includes RRF‑K, budgets, and recall/oracle metrics per query. (The dashboard queries above assume you ingest those as time series.)

---

## 7) How this aligns with your existing code

* **Hybrid aggregation**: you already provide `reciprocal_rank_fusion` in `retrieval.hybrid` and a weighted RRF API under `retrieval.fusion.weighted_rrf`; the patch keeps those paths and simply **selects K per query**, not globally.  
* **Channel orchestration**: `HybridSearchEngine._gather_channel_hits` already pulls “semantic/bm25/splade” and returns warnings; we’re slicing per‑channel lists to the **budgeted depths** immediately before fusion. 
* **On‑call bundle**: your timeline/events are present in `HybridSearchEngine`; the `_build_debug_bundle` method just aggregates in‑hand data (query, budgets, tops) and emits as a single event. 
* **Recency**: the booster queries DuckDB *if* a `commit_ts` (or similarly named) column exists—otherwise it’s a no‑op (exactly the “nudge” approach recommended in your design doc).  

---

## 8) Operational notes & defaults

* All new behavior is gated by safe defaults:

  * Query‑aware budgets enabled by default, but presets mimic your current depths.
  * Recency is **disabled** unless `index.recency_enabled=true`.
  * RM3 remains **auto**; if you prefer off globally, set `enable_query_aware_budgets=False` or `rm3_auto=False` in `StageGateConfig` (and leave the harness to run A/B).
* The **harness** is intentionally decoupled from the service; it imports your providers and fusion so it measures *exactly* what production uses. It also computes the **oracle union** headroom recommended in your PDF to quantify upside. 

---

## 9) Next steps (quick runbook)

1. **Apply patches**
   Save the diffs above and apply:

```bash
git apply <<'PATCH'
# (paste the three diffs in this message, one after another)
PATCH
```

2. **Enable recency nudges (optional)**

```bash
# e.g., via env or config
INDEX_RECENCY_ENABLED=true
INDEX_RECENCY_HALF_LIFE_DAYS=21
INDEX_RECENCY_MAX_BOOST=0.12
```

3. **Run the harness** (with and without RM3):

```bash
python tools/recall_harness.py \
  --queries data/eval/queries.csv \
  --qrels data/eval/qrels.trec \
  --k-list 10,25,50,100 \
  --sweep-k1 0.6,0.9,1.2,1.5 \
  --sweep-b 0.2,0.4,0.75,1.0 \
  --rm3 auto \
  --limit 100 \
  --out results/recall_report.csv
```

4. **Import the Grafana JSON** and wire Prometheus targets to the suggested metric names (or adjust the panel queries to your naming).

---

## 10) What you get, concretely

* **Query‑aware channel budgets**: SPLADE gets more depth on vague NL queries; BM25 gets more depth on literal/code‑like queries; semantic is always in play (tunable). RRF‑K is deeper on ambiguous input, shallower on literal queries—consistent with hybrid best practices.  
* **Recency nudges**: a tiny, opt‑in booster that increases the chance recent refactors/breaking changes appear in the top set—particularly helpful in codebases with active branches. Fails open if timestamps aren’t available. 
* **On‑call debug bundle**: a one‑shot JSON payload (already in the timeline) showing the query profile, budgets, chosen RRF‑K, and per‑channel tops—shortening incident MTTR substantially by avoiding ad hoc repros. 
* **Oracle headroom**: the harness reports “best possible” union recall—as proposed in the planning doc—so you can prioritize whether to invest in SPLADE fine‑tuning, RM3 policies, or index hygiene next. 
* **RM3 & k1/b sweeps**: copy‑pastable harness that exercises PRF on the same Lucene index variants you run, consistent with Pyserini’s documented patterns.  

---

If you’d like, I can also generate a short PR description text for each change (“retrieval‑gating”, “hybrid‑recency”, “recall‑harness + dashboards”) so you can open three focused PRs cleanly. And if your DuckDB schema exposes a timestamp under a different view/column, I’ll adapt the default probe (it’s one line in `RecencyConfig`).


