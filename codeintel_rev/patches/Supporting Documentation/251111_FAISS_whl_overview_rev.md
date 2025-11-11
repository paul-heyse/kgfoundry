Below is a practical, end‑to‑end guide to **what’s actually inside your FAISS wheel** and how to use it to design fast, correct CPU/GPU vector workflows. I’ve done two things in parallel:

* **Inspected your uploaded wheel** (`faiss-1.12.0-py3-none-any.whl`) to inventory the concrete symbols (index classes, functions, helpers) it exposes.
* **Cross‑checked behavior, parameters, and best‑practices** against the FAISS docs/wiki and recent GPU/cuVS material.

---

## What’s in *your* wheel (quick facts)

* **Version & layout.** The wheel bundles multiple CPU variants and GPU bindings:

  * Python wrappers for **baseline, AVX2, and AVX‑512 (Sapphire Rapids)**: `swigfaiss.py`, `swigfaiss_avx2.py`, `swigfaiss_avx512_spr.py`.
  * GPU wrappers (CUDA/cuVS integration class names are present): e.g., `StandardGpuResources`, `GpuIndexFlat*`, `GpuIndexIVF*`, `GpuIndexIVFPQ*`, **`GpuIndexCagra`**, `GpuClonerOptions`, `GpuMultipleClonerOptions`, and GPU conversion helpers such as `index_cpu_to_gpu`, `index_cpu_to_gpu_multiple`, `index_gpu_to_cpu`. ([GitHub][1])
* **Graph indexes (CPU & GPU)** present by name: `IndexHNSW*`, `IndexNSG*`, and GPU‑side **CAGRA** (`GpuIndexCagra`) which is the cuVS graph index. ([Faiss][2])
* **Quantization families:** `IndexIVFPQ*` (incl. `IndexIVFPQFastScan`), `IndexIVFScalarQuantizer*`, `ProductQuantizer`, `ResidualQuantizer`, `AdditiveQuantizer`, OPQ matrices, etc. ([Faiss][3])
* **Binary vector indexes:** `IndexBinaryFlat`, `IndexBinaryIVF`, `IndexBinaryHNSW` (+ variants). (Binary dim must be a multiple of 8; Hamming metric.) ([GitHub][4])
* **I/O & tuning utilities:** `read_index`, `write_index`, `serialize_index`, `deserialize_index`, `clone_index`, `index_factory`, `ParameterSpace`, `OperatingPoints`. *(Note: GPU indexes must be converted to CPU before writing to disk.)* ([GitHub][5])
* **GPU utilities & KNN:** `get_num_gpus`, `gpu_profiler_*`, `bfKnn`/`bruteForceKnn` (brute‑force on GPU memory buffers). ([Faiss][6])

> **Full inventory (from your wheel).** I generated a machine‑readable symbol list (classes & functions, grouped by category).
> **[Download the CSV](sandbox:/mnt/data/faiss_1_12_0_api_inventory.csv)** · **[Download the JSON](sandbox:/mnt/data/faiss_1_12_0_api_inventory.json)**

**Packaging note (important).** Your wheel’s `WHEEL` metadata says **`Root-Is-Purelib: true`** with a filename tag of **`py3-none-any`**, yet it contains compiled `.so` modules. That’s a platform wheel packaged as if it were pure‑Python. It may install on incompatible platforms. Correct wheels should use platform/ABI tags and set purelib/platlib appropriately (see PEP‑427). ([Python Enhancement Proposals (PEPs)][7])

---

## The major *user‑level operations* you’ll use everywhere

The FAISS Python API exposes a small set of **core operations** across all index types (CPU or GPU). You’ll combine these to build workflows:

| Operation                                                                                       | What it does                                                                                         | Where used                                                                             |
| ----------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `train(x)`                                                                                      | Learn coarse quantizer/codebooks (IVF/PQ/AQ/RQ) from samples `x`.                                    | All trained indexes (e.g., `IVF*`, `PQ*`), not needed for Flat/HNSW/NSG. ([GitHub][8]) |
| `add(x)` / `add_with_ids(x, ids)`                                                               | Insert vectors; `add_with_ids` lets you control FAISS IDs (use an `IDMap` if you need external IDs). | Any index                                                                              |
| `search(xq, k)`                                                                                 | k‑NN search (returns distances `D` and ids `I`).                                                     | Any index (k‑NN is mandatory) ([Faiss][9])                                             |
| `range_search(xq, radius)`                                                                      | All neighbors within a radius; Python returns `(lims, D, I)`.                                        | Many indexes (not all GPU variants implement it) ([GitHub][10])                        |
| `remove_ids(sel)` / `reset()`                                                                   | Delete or clear.                                                                                     | Supported by many indexes; HNSW has limits. ([GitHub][11])                             |
| `reconstruct(id)` / `reconstruct_batch(ids)` / `search_and_reconstruct(...)`                    | Decode stored vectors. Useful for refinement, debugging, and export.                                 | Composite/PQ/IVF; see “Special operations” wiki. ([GitHub][10])                        |
| I/O & clone: `write_index`, `read_index`, `serialize_index`, `deserialize_index`, `clone_index` | Save/restore/duplicate CPU indexes. (**GPU must be converted to CPU first**.)                        | Persistence, replication, duplication ([GitHub][5])                                    |

**Tuning at runtime:** Prefer the high‑level **`ParameterSpace`** to set parameters on “opaque” (composite) indexes:

```python
ps = faiss.ParameterSpace()
ps.set_index_parameters(index, "nprobe=32,quantizer_efSearch=128")
```

Supported knobs include (per FAISS docs): `nprobe` (IVF), `efSearch` (HNSW), `ht` (polysemous for PQ), `k_factor` (IVFPQR/refine), etc. The `quantizer_` prefix targets the IVF’s coarse quantizer (e.g., `IVF_HNSW32`). Auto‑tuning explores Pareto‑optimal operating points. ([GitHub][5])

---

## CPU indexes you have – what they do & how to configure

Below are the **families** you’ll actually choose among; I’m including the **key parameters** you should expect to tune.

### 1) **Flat (exact)**

* **Classes:** `IndexFlatL2`, `IndexFlatIP` (and a generic `IndexFlat`).
* **Operation:** brute‑force exact k‑NN over all vectors. Baseline for quality; useful for small n or as a second‑stage reranker.
* **Parameters:** none (but **threads** matter).
* **Factory strings:** `"Flat"` or `"Flat,IDMap"` to map IDs. ([Faiss][12])

### 2) **IVF (inverted files)**

* **Classes:** `IndexIVFFlat`, `IndexIVFPQ`, `IndexIVFScalarQuantizer`, `IndexIVF(Additive/Residual/LocalSearch)Quantizer*` and fast‑scan variants (`IndexIVFPQFastScan`).
* **Operation:** cluster data into **`nlist`** coarse cells; at search, probe top **`nprobe`** cells and scan only those vectors. `IVFFlat` stores raw vectors; `IVFPQ` compresses them with **PQ**; `IVF(SQ)` uses scalar quantization. ([Faiss][13])
* **Key params:**

  * **Build‑time:** `nlist` (coarse centroids), PQ shape `m` and `nbits` (e.g., `PQ64x8`), or SQ type.
  * **Search‑time:** **`nprobe`** (more probes → higher recall, higher latency), `max_codes` (IMI special), and PQ polysemous **`ht`** if applicable. ([GitHub][5])
* **FastScan:** `IndexIVFPQFastScan` (4‑bit PQ with packed codes for register‑resident LUTs; very fast). ([Faiss][3])
* **Factory strings:** `"IVF4096,Flat"`, `"IVF4096,PQ64"`, `"OPQ16_64,IVF4096,PQ64"`, `"IVF_HNSW32,Flat"` (HNSW coarse quantizer). ([GitHub][14])

### 3) **PQ/AQ/RQ (standalone quantizers)**

* **Classes:** `IndexPQ`, `ProductQuantizer`, `ResidualQuantizer`, `AdditiveQuantizer` (+ product/local‑search variants).
* **Operation:** compress vectors into **m** sub‑quantizers (PQ) or additive/residual codebooks; search in compressed (or partially refined) space. ([Faiss][15])
* **Key params:** `m`, `nbits` (codebook size), training `train_type`, optional OPQ front‑end (`OPQMatrix`). ([Faiss][15])

### 4) **Graph family (HNSW & NSG)**

* **Classes:** `IndexHNSWFlat`, `IndexHNSWPQ`, `IndexHNSWSQ`, `IndexNSG*`.
* **Operation:** navigable small‑world / neighbor graph search.
* **Key params (HNSW):** **`M`**, **`efConstruction`**, **`efSearch`** (more = better recall, more mem/latency). ([GitHub][16])

### 5) **Binary indexes**

* **Classes:** `IndexBinaryFlat`, `IndexBinaryIVF`, `IndexBinaryHNSW`, `IndexBinary(Multi)Hash`.
* **Operation:** Hamming distance over packed bits; dimension must be multiple of 8. Great for byte‑quantized or pure binary features. ([GitHub][4])

---

## GPU indexes & utilities available in your wheel

### 1) **Core GPU path (classic FAISS GPU)**

* **Resources:** `StandardGpuResources` (temp memory, streams, cuBLAS handles). By default it reserves a chunk of VRAM for scratch (historically “≈2 GB on a 12 GB GPU”). Use `setTempMemory()` to change it. ([GitHub][1])
* **Index classes:** `GpuIndexFlatL2/IP`, `GpuIndexIVFFlat`, `GpuIndexIVFPQ`.
* **Moving indexes:** `index_cpu_to_gpu`, `index_cpu_to_gpu_multiple` (replicate or **shard** via `GpuMultipleClonerOptions.shard`), and `index_gpu_to_cpu`. You **cannot** write a GPU index directly to disk—convert to CPU first. ([GitHub][5])
* **Cloner options:** `GpuClonerOptions` / `GpuMultipleClonerOptions` — control index storage (indices type), float16 usage, precomputed tables, memory space, sharding, common coarse quantizer, etc. ([Faiss][17])
* **Brute‑force GPU KNN:** direct KNN on device memory (e.g., “bfKnn”), and the `faiss::gpu` distance API. Handy for ground‑truth/reranking. ([Faiss][6])
* **Threading caveat:** FAISS GPU indices are **not thread‑safe**; use a distinct `StandardGpuResources` per CPU thread. ([GitHub][18])

### 2) **cuVS / CAGRA path (new GPU backend)**

Your wheel contains symbols that enable cuVS (RAPIDS) integrations:

* **`GpuIndexCagra`** (GPU graph index optimized for small‑batch queries), and configs like `GpuIndexCagraConfig` with `use_cuvs` toggles. ([Faiss][2])
* **cuVS integration** supports GPU **Flat**, **IVF‑Flat**, **IVF‑PQ**, and **CAGRA**; brings faster builds and lower latency at target recall. Multi‑GPU is currently **not** supported for cuVS indexes. ([RAPIDS Docs][19])
* **Hybrid build trick:** You can use a GPU **CAGRA** index to bootstrap/initialize CPU **HNSW** (`IndexHNSWCagra`) to accelerate CPU graph builds. ([GitHub][20])

> **Tip.** To see what this wheel was built with at runtime, call:
>
> ```python
> import faiss
> print(faiss.get_compile_options())
> ```
>
> This string reveals compile‑time toggles (e.g., CUDA/cuVS, BLAS). ([Faiss][21])

---

## The **index factory** you’ll rely on constantly

`faiss.index_factory(d, "…")` parses a concise string into a potentially **composite** index: preprocessing → coarse quantizer (IVF) → encoder (PQ/SQ) → (optional) refine. A few useful patterns:

* **Exact:** `"Flat"`
* **IVF no compression:** `"IVF4096,Flat"`
* **IVF+PQ:** `"IVF4096,PQ64"` or `"OPQ16_64,IVF4096,PQ64"` for orthogonal pre‑rotation
* **HNSW coarse IVF:** `"IVF_HNSW32,Flat"`
* **Refine with Flat:** `"IVF4096,PQ64,Refine(Flat)"`
  FAISS’s wiki lists the grammar and components in detail. ([GitHub][14])

---

## Parameter tuning cheat‑sheet (what to dial and when)

**Primary runtime knobs (via `ParameterSpace`):**

* **IVF/IMI:** `nprobe` (speed/recall trade‑off), `max_codes` for IMI.
* **HNSW:** `efSearch` (search effort; build‑time **`efConstruction`**).
* **PQ:** polysemous `ht`; **IVFPQR/Refine:** `k_factor`/`kf_factor` for reranking.
  For IVF with an HNSW **coarse quantizer**, set `quantizer_efSearch`. ([GitHub][5])

**Build‑time rules of thumb** (CPU or GPU):

* **`nlist`** roughly **≈ sqrt(N)** for million‑scale; adjust up with higher dims/long‑tail distributions. **Always train** IVF/PQ on a representative sample (often `max(100k, 100*nlist)`). ([Pinecone][22])
* **PQ shape (`m`, `nbits`)**: start with `m ≈ d/2` and `nbits=8`, then shrink bits for memory; consider **FastScan** for 4‑bit PQ if you accept its constraints. ([GitHub][23])
* **HNSW:** raise `M` and `efConstruction` for better recall; tune `efSearch` at query time. ([GitHub][16])

---

## “Special operations” & composite/distributed patterns

* **Refinement:** `IndexRefine` or post‑reranking with a Flat index (factory `…,Refine(Flat)`) to recover accuracy at small extra cost. ([GitHub][5])
* **Shards vs Replicas (multi‑GPU/host):** `index_cpu_to_gpu_multiple` defaults to **replicas**; set `GpuMultipleClonerOptions.shard=True` to shard. For IVF, `common_ivf_quantizer=True` shares the coarse quantizer across GPUs. ([GitHub][1])
* **Sharded/replicated CPU:** `IndexShards*` and `IndexReplicas*` compose multiple sub‑indexes. ([Faiss][24])
* **Binary vectors:** switch to the **Binary** family when your embedding pipeline emits bit codes; it’s Hamming distance only. ([GitHub][4])

---

## What likely changed vs your previous (mis‑)build & how to validate

Given your note that a prior wheel was “incorrectly compiled,” here are **symptoms** you might have seen and how to **check** them now:

1. **Missing GPU entry points** (no `StandardGpuResources`, `index_cpu_to_gpu`, or `GpuIndex*` symbols).
   **Check now:** `hasattr(faiss, "StandardGpuResources")`, or just run `faiss.get_num_gpus()`; if the symbol exists but returns `0`, it’s fine (no GPU present). ([GitHub][1])

2. **Instruction set selection wrong** (e.g., slow Flat distance on AVX‑capable CPUs).
   **Check now:** This wheel bundles AVX2 and AVX‑512‑SPR loaders and automatically selects the best at import. You can force fallback via **`FAISS_DISABLE_CPU_FEATURES=1`** for debugging (environment variable consults the loader). *(This behavior comes from the loader in your wheel.)*

3. **Unable to write GPU indexes.**
   **Expected behavior:** FAISS does not support writing GPU indexes; convert to CPU with `index_gpu_to_cpu` before `write_index`. ([GitHub][5])

4. **cuVS behavior toggles.**
   If you rely on CAGRA/IVF cuVS implementations, ensure the build enabled cuVS or set the per‑index config `use_cuvs=True`. Validate with `faiss.get_compile_options()` and via performance characteristics. ([GitHub][25])

---

## CPU vs GPU: when to pick which

* **GPU Flat:** best for exact reranking or small‑to‑medium datasets with batched queries; trivial to use; extremely fast on modern GPUs. ([RAPIDS Docs][26])
* **GPU IVF‑Flat / IVF‑PQ:** strong for million‑to‑billion scale; move training and add/search to GPU for throughput. With **cuVS**, both build and search improve substantially (order‑of‑magnitude in some cases). ([NVIDIA Developer][27])
* **GPU CAGRA vs CPU HNSW:** CAGRA shines on **small‑batch** latency at high recall; you can even use it to **seed** a CPU HNSW. ([NVIDIA Developer][28])
* **Threading:** GPU path isn’t thread‑safe—one `StandardGpuResources` per thread. CPU path is multi‑threaded with OpenMP. ([GitHub][18])

---

## Minimal “good” recipes (copy/paste)

**A) IVF‑PQ on CPU with tuning + persistence**

```python
import faiss, numpy as np
d = 768
index = faiss.index_factory(d, "OPQ16_64,IVF4096,PQ64", faiss.METRIC_L2)  # factory string
xt = np.random.randn(300_000, d).astype("float32")
xb = np.random.randn(10_000_000, d).astype("float32")
xq = np.random.randn(1000, d).astype("float32")

index.train(xt)                       # required for IVF/PQ
index.add(xb)                         # add vectors
ps = faiss.ParameterSpace()
ps.set_index_parameters(index, "nprobe=64")  # runtime tuning
D, I = index.search(xq, k=10)

faiss.write_index(index, "ivfpq.index")      # save (CPU only)
idx2 = faiss.read_index("ivfpq.index")       # load
```

(Factory strings and tuning parameters from FAISS docs. Save/load is CPU‑only.) ([GitHub][14])

**B) Move an existing CPU index to 4 GPUs (replicas vs shards)**

```python
res = faiss.StandardGpuResources()
# Single GPU
gpu = faiss.index_cpu_to_gpu(res, 0, index)

# Multi‑GPU replicate:
gpu_repl = faiss.index_cpu_to_gpu_multiple([faiss.StandardGpuResources() for _ in range(4)],
                                           [0,1,2,3], index)

# Multi‑GPU shard:
opt = faiss.GpuMultipleClonerOptions()
opt.shard = True
gpu_shards = faiss.index_cpu_to_gpu_multiple([faiss.StandardGpuResources() for _ in range(4)],
                                             [0,1,2,3], index, opt)
```

(Defaults replicate; use `opt.shard=True` for sharding; you can set `common_ivf_quantizer=True` for IVF.) ([GitHub][1])

**C) GPU CAGRA (if built with cuVS)**

```python
cfg = faiss.GpuIndexCagraConfig()
cfg.use_cuvs = True
res = faiss.StandardGpuResources()
gpu_cagra = faiss.GpuIndexCagra(res, d, faiss.METRIC_L2, 0, cfg)
gpu_cagra.train(xt)
gpu_cagra.add(xb)
D, I = gpu_cagra.search(xq, 10)
```

(CAGRA and `use_cuvs` flag; see GPU–cuVS docs.) ([GitHub][25])

---

## Designing effective vector workflows (rules of thumb)

1. **Pick the family first, then tune.**

   * **Flat** when N is small or as a **rerank** stage.
   * **HNSW** for high recall on CPU when updates are frequent; tune `M`, `efConstruction`, `efSearch`. ([GitHub][16])
   * **IVF+PQ** for large scale; tune `nlist`, `nprobe`, PQ shape; consider **FastScan** (4‑bit). ([GitHub][5])

2. **Train on representative data.** For IVF, use ≥ `max(100k, 100*nlist)` training points; ensure embeddings match serving distribution. ([Gitee][29])

3. **Separate build‑time vs search‑time knobs.** Encode build choices in the factory string; keep search knobs in `ParameterSpace` so you can A/B **without rebuilding** the index. ([GitHub][5])

4. **GPU memory is precious.** Control scratch space via `StandardGpuResources.setTempMemory()`. For IVF on GPU, `reserveVecs` before add to avoid reallocation; convert to CPU before saving. ([Faiss][30])

5. **Compose for throughput.** Shard across GPUs/hosts with shared quantizer; use replicas for QPS scaling; refine top‑K with Flat on CPU or GPU. ([GitHub][1])

6. **Binary vectors & byte embeddings.** If you quantize embeddings to bytes, FAISS **binary** indexes with Hamming distance can be dramatically lighter/faster. ([OpenSearch][31])

---

## Appendix A — concrete symbols present (high‑level)

From your wheel:

* **Index families (non‑exhaustive examples):**
  `IndexFlatL2/IP`; `IndexIVFFlat`, `IndexIVFPQ`, `IndexIVFScalarQuantizer`, `IndexIVFPQFastScan`;
  `IndexHNSWFlat`, `IndexHNSWPQ`, `IndexHNSWSQ`; `IndexNSG*`;
  `IndexBinaryFlat/IVF/HNSW`;
  `IndexRefine`, `IndexPreTransform`, `IndexShards*`, `IndexReplicas*`.

* **Transforms / preprocessing:** `OPQMatrix`, `PCAMatrix`, `ITQTransform`, `NormalizationTransform`, `RandomRotationMatrix`.

* **Quantizers:** `ProductQuantizer`, `ResidualQuantizer`, `AdditiveQuantizer` (+ product/local‑search variants).

* **GPU:** `StandardGpuResources`, `GpuIndexFlat*`, `GpuIndexIVFFlat`, `GpuIndexIVFPQ`, **`GpuIndexCagra`**, `GpuClonerOptions`, `GpuMultipleClonerOptions`, `index_cpu_to_gpu(_multiple)`, `index_gpu_to_cpu`, `get_num_gpus`, `isGpuIndex`.

* **I/O & tuning:** `write_index`, `read_index`, `serialize_index`, `deserialize_index`, `clone_index`, `index_factory`, `ParameterSpace`, `OperatingPoints`.

* **Contrib helpers (Python):**
  `contrib.ivf_tools` (pre‑assigned add/search), `contrib.big_batch_search`, `contrib.exhaustive_search` (GPU range search helpers), `contrib.evaluation` (PR curves, KNN intersection), `contrib.factory_tools.get_code_size`, `contrib.ondisk`, `contrib.torch_utils`. *(These are Python helpers layered on top of the core C++ API.)*

> For the exhaustive, symbol‑by‑symbol list, use the CSV/JSON linked at the top.

---

## Appendix B — reference links used here

* **FAISS main docs & wiki:** overview, indexes, factory grammar, special ops, I/O, tuning. ([Faiss][12])
* **CPU API details:** C++ docs for core classes (`Index`, `IndexIVFFlat`, `RangeSearchResult`, etc.). ([Faiss][9])
* **GPU docs:** GPU overview, StandardGpuResources, cloners, multi‑GPU options. ([GitHub][1])
* **cuVS integration & CAGRA:** what’s supported, limitations, usage. ([GitHub][25])
* **FastScan:** 4‑bit PQ fast‑scan impl. ([GitHub][23])
* **Binary indexes:** overview & constraints. ([GitHub][4])
* **Wheel format note:** why `py3-none-any` / `Root-Is-Purelib: true` is not appropriate for binary wheels. ([Python Enhancement Proposals (PEPs)][7])

---

## Suggested validation checklist for your environment

1. **Confirm compile flags**: `print(faiss.get_compile_options())` (look for CUDA/cuVS flags). ([Faiss][21])
2. **Probe GPU path**: `faiss.get_num_gpus()`, build a tiny `GpuIndexFlatL2`, run a 1K‑by‑1K search. ([GitHub][1])
3. **Exercise factory & persistence**: build `IVF4096,PQ64` on a sample, `write_index/read_index`. ([GitHub][5])
4. **Tune with `ParameterSpace`**: run a sweep over `nprobe`/`efSearch` and record recall‑latency curves. ([GitHub][5])

If you want, I can also produce **ready‑to‑run correctness & performance smoke tests** tailored to your dataset shapes and metrics (L2 vs IP), but the guide above should be enough to rebuild confidence in the module and to (re)design efficient CPU/GPU workflows with your current build.

[1]: https://github.com/facebookresearch/faiss/wiki/Faiss-on-the-GPU?utm_source=chatgpt.com "Faiss on the GPU · facebookresearch/faiss Wiki"
[2]: https://faiss.ai/cpp_api/struct/structfaiss_1_1gpu_1_1GpuIndexCagra.html?utm_source=chatgpt.com "Struct faiss::gpu::GpuIndexCagra"
[3]: https://faiss.ai/cpp_api/file/IndexIVFPQFastScan_8h.html?utm_source=chatgpt.com "File IndexIVFPQFastScan.h"
[4]: https://github.com/facebookresearch/faiss/wiki/Binary-indexes?utm_source=chatgpt.com "Binary Indexes · facebookresearch/faiss Wiki"
[5]: https://github.com/facebookresearch/faiss/wiki/Index-IO%2C-cloning-and-hyper-parameter-tuning "Index IO, cloning and hyper parameter tuning · facebookresearch/faiss Wiki · GitHub"
[6]: https://faiss.ai/cpp_api/namespace/namespacefaiss_1_1gpu.html?utm_source=chatgpt.com "Namespace faiss::gpu"
[7]: https://peps.python.org/pep-0427/?utm_source=chatgpt.com "PEP 427 – The Wheel Binary Package Format 1.0"
[8]: https://github.com/facebookresearch/faiss/wiki/Index-IO%2C-cloning-and-hyper-parameter-tuning?utm_source=chatgpt.com "Index IO, cloning and hyper parameter tuning"
[9]: https://faiss.ai/cpp_api/struct/structfaiss_1_1Index.html?utm_source=chatgpt.com "Struct faiss::Index"
[10]: https://github.com/facebookresearch/faiss/wiki/Special-operations-on-indexes?utm_source=chatgpt.com "Special operations on indexes · facebookresearch/faiss Wiki"
[11]: https://github.com/facebookresearch/faiss/wiki/Guidelines-to-choose-an-index?utm_source=chatgpt.com "Guidelines to choose an index · facebookresearch/faiss Wiki"
[12]: https://faiss.ai/index.html?utm_source=chatgpt.com "Welcome to Faiss Documentation — Faiss documentation"
[13]: https://faiss.ai/cpp_api/struct/structfaiss_1_1IndexIVFFlat.html?utm_source=chatgpt.com "Struct faiss::IndexIVFFlat"
[14]: https://github.com/facebookresearch/faiss/wiki/The-index-factory?utm_source=chatgpt.com "The index factory · facebookresearch/faiss Wiki"
[15]: https://faiss.ai/cpp_api/struct/structfaiss_1_1ProductQuantizer.html?utm_source=chatgpt.com "Struct faiss::ProductQuantizer"
[16]: https://github.com/facebookresearch/faiss/wiki/Faiss-indexes?utm_source=chatgpt.com "Faiss indexes · facebookresearch/faiss Wiki"
[17]: https://faiss.ai/cpp_api/struct/structfaiss_1_1gpu_1_1GpuClonerOptions.html?utm_source=chatgpt.com "Struct faiss::gpu::GpuClonerOptions"
[18]: https://github.com/facebookresearch/faiss/wiki/Threads-and-asynchronous-calls?utm_source=chatgpt.com "Threads and asynchronous calls · facebookresearch/faiss ..."
[19]: https://docs.rapids.ai/api/cuvs/nightly/integrations/faiss/?utm_source=chatgpt.com "Faiss — cuvs"
[20]: https://github.com/facebookresearch/faiss/wiki/GPU-Faiss-with-cuVS-usage?utm_source=chatgpt.com "GPU Faiss with cuVS usage"
[21]: https://faiss.ai/cpp_api/file/utils_8h.html?utm_source=chatgpt.com "File utils.h"
[22]: https://www.pinecone.io/learn/series/faiss/faiss-tutorial/?utm_source=chatgpt.com "Introduction to Facebook AI Similarity Search (Faiss)"
[23]: https://github.com/facebookresearch/faiss/wiki/Fast-accumulation-of-PQ-and-AQ-codes-%28FastScan%29?utm_source=chatgpt.com "Fast accumulation of PQ and AQ codes (FastScan)"
[24]: https://faiss.ai/cpp_api/file/IndexShards_8h.html?utm_source=chatgpt.com "File IndexShards.h"
[25]: https://github.com/facebookresearch/faiss/wiki/GPU-Faiss-with-cuVS?utm_source=chatgpt.com "GPU Faiss with cuVS"
[26]: https://docs.rapids.ai/api/cuvs/stable/cuvs_bench/param_tuning/?utm_source=chatgpt.com "cuVS Bench Parameter Tuning Guide"
[27]: https://developer.nvidia.com/blog/enhancing-gpu-accelerated-vector-search-in-faiss-with-nvidia-cuvs/?utm_source=chatgpt.com "Enhancing GPU-Accelerated Vector Search in Faiss with ..."
[28]: https://developer.nvidia.com/blog/accelerating-vector-search-fine-tuning-gpu-index-algorithms/?utm_source=chatgpt.com "Accelerating Vector Search: Fine-Tuning GPU Index ..."
[29]: https://gitee.com/chenjun2hao/Faiss.learning/blob/master/benchs/bench_polysemous_1bn.py?utm_source=chatgpt.com "chenjun2hao/Faiss.learning"
[30]: https://faiss.ai/cpp_api/class/classfaiss_1_1gpu_1_1StandardGpuResources.html?utm_source=chatgpt.com "Class faiss::gpu::StandardGpuResources"
[31]: https://opensearch.org/blog/faiss-byte-vector/?utm_source=chatgpt.com "Introducing byte vector support for Faiss in the ..."
