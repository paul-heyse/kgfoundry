Below is a **field‑tested, implementation‑grade guide** to the **vLLM** Python library **as of v0.11.0**—organized for an autonomous AI engineering agent to build and operate advanced, production‑class deployments.

> TL;DR: v0.11.0 makes **V1 the only engine** (V0 fully removed), turns on a faster **CUDA graph mode** by default, grows **model/quantization coverage**, adds **KV‑cache CPU offload**, and expands **disaggregated serving**, **speculative decoding**, **structured outputs**, **tool calling**, **metrics**, and **LoRA** ergonomics. ([GitHub][1])

---

## 1) What changed in **v0.11.0** (upgrade‑critical facts)

**Highlights**

* **V0 engine removed**. V1 is now the only engine. (Breaking: V0 classes such as `AsyncLLMEngine`, `LLMEngine`, `MQLLMEngine` are gone.) ([GitHub][1])
* **Default CUDA graph mode**: `FULL_AND_PIECEWISE` enabled for higher perf, esp. fine‑grained MoE. ([GitHub][1])
* **Known caveat**: `--async-scheduling` can produce gibberish in **v0.11.0**/**v0.10.2**—correct in **v0.10.1**; fix is in progress. (Avoid in prod.) ([GitHub][1])
* **Model/feature additions**: support for **Qwen3‑VL**, **Qwen3‑Next**, **OLMo3**, **LongCat‑Flash**, new encoders, **BERT NER**, **spec‑decode** integrations, and numerous perf patches. ([GitHub][1])
* **Engine core**: **KV‑cache CPU offloading (LRU)**, prompt embeddings, sharded‑state loading, FlexAttention sliding window, hybrid allocators, FlashAttention/FlashInfer improvements. ([GitHub][1])
* **Large‑scale**: Dual‑Batch Overlap, data/expert parallel refinements, disaggregated serving metrics/connectors. ([GitHub][1])
* **Quantization**: FP8/NVFP4 & related kernels, faster preprocessing; broader catalog (GPTQ/AWQ/FP8/INT8/INT4, GGUF experimental). ([GitHub][1])

**Compatibility signal**: NVIDIA’s 25.09 container (CUDA **13.0**) shipped with vLLM **0.10.1.1** and proves the CUDA‑13 stack path; v0.11.0 builds on the same lineage. (Use this to validate drivers and container baselines.) ([NVIDIA Docs][2])

---

## 2) Core mental model: **V1 Engine** + **PagedAttention** + **continuous batching**

* **PagedAttention** = virtual‑memory‑like KV cache paging → near‑zero waste and shared reuse across requests. Read the design & paper for correctness/perf claims and kernel mechanics. ([VLLM Documentation][3])
* **Continuous batching** = keeps GPUs saturated by mixing prefill/decode tokens across requests; V1 couples this with CUDA/HIP graphs and multi‑parallelism. ([VLLM Documentation][4])
* **Prefix caching** & **chunked prefill** reduce repeated prompt work and improve long‑context throughput; V1 exposes tunables for both. ([VLLM Documentation][5])

---

## 3) Install & runtime targets

* **GPU targets**: install from PyPI or source; pick per‑device install docs (CUDA, ROCm, XPU, CPU). Use vendor wheels/containers for faster onboarding. ([VLLM Documentation][6])
* **Quick pip**: `pip install vllm` (ensure a compatible PyTorch/CUDA/driver stack). ([PyPI][7])
* **Notes for developers**: editable installs with precompiled kernels are documented (UV workflows, incremental compilation), helpful when iterating on C++/CUDA. ([VLLM Documentation][6])

---

## 4) Python **offline inference** APIs (V1)

### 4.1 Minimal generation

```python
from vllm import LLM, SamplingParams

llm = LLM(model="meta-llama/Llama-3.1-8B-Instruct")   # V1 under the hood
params = SamplingParams(temperature=0.2, top_p=0.9, max_tokens=128)
outs = llm.generate(["Explain PagedAttention in 2 lines."], sampling_params=params)
print(outs[0].outputs[0].text)
```

`SamplingParams` mirrors OpenAI’s semantics and adds extras (beam search, logprobs, etc.). ([VLLM Documentation][8])

### 4.2 Streaming / async

* Use the async example to stream tokens while keeping continuous batching. ([VLLM Documentation][9])

### 4.3 **Embeddings / pooling / classification / scoring**

* **Embedding**: `LLM.embed(prompts)` for pooling models. ([VLLM Documentation][10])
* **Classification/Score**: `LLM.classify` and `LLM.score` (cross‑encoders / rerankers). The OpenAI‑compatible **Score API** is also available on the server. ([VLLM Documentation][10])

### 4.4 **Prefix caching** (automatic)

* Reuses KV blocks across requests sharing a common prefix. Works out of the box; see example & design notes for behavior. ([VLLM Documentation][5])

### 4.5 **Speculative decoding**

* First‑class feature with examples; integrates with FlashInfer/EAGLE paths depending on model. ([VLLM Documentation][11])

### 4.6 **Multimodal**

* Input images/audio/video via processors + multimodal tensors; OpenAI server accepts multimodal chat payloads. ([VLLM Documentation][12])

### 4.7 **Prompt embeddings (text or multimodal)**

* You can pass **`prompt_embeds`** (pre‑computed embeddings); must be enabled in engine/serve args due to graph compilation. ([VLLM Documentation][13])

---

## 5) **OpenAI‑compatible server** (`vllm serve`)

The server implements **Completions**, **Chat Completions**, **Embeddings**, **Transcription**, **Classification/Score**, and more; you can call it with the official OpenAI client. ([VLLM Documentation][14])

### 5.1 Start the server (typical)

```bash
vllm serve \
  --model meta-llama/Llama-3.1-8B-Instruct \
  --tensor-parallel-size 2 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.92 \
  --enable-chunked-prefill \
  --enable-prefix-caching
```

* Full CLI & JSON args are documented; tune TP/PP/DP/EP and batching thresholds here. ([VLLM Documentation][15])

### 5.2 Tool calling & structured outputs

* **Tool calling**: server supports OpenAI tools with **model‑specific parsers** (e.g., **Pythonic** tool parser for Llama 3.2/4). ([VLLM Documentation][16])
* **Structured outputs**: regex / JSON‑schema / grammar backends (xgrammar/guidance). Configure via `SamplingParams` (or OpenAI payload). ([VLLM Documentation][17])

### 5.3 LoRA (dynamic, per‑request; multi‑LoRA)

* Dynamically **load/unload** adapters via REST (`/v1/load_lora_adapter`, `/v1/unload_lora_adapter`) and select per request. See API pages & examples (and compatibility constraints like excluding `lm_head` in LoRA). ([VLLM Documentation][18])

### 5.4 Embeddings at scale

* Server exposes `/v1/embeddings` and offers **long‑text chunked embedding** examples. ([VLLM Documentation][19])

### 5.5 Audio / transcription

* Examples for OpenAI‑style transcription clients (e.g., Whisper). ([VLLM Documentation][20])

### 5.6 Metrics & dashboards

* `/metrics` endpoint (Prometheus) + ready‑made Grafana dashboards; catalog of metric names and PromQL hints are documented. ([VLLM Documentation][21])

> **One model per vLLM process.** If you need multiple base models on one logical endpoint, front several `vllm serve` processes with a router (e.g., Nginx) and route by path/host—exactly the design assumed in the accompanying architecture. 

---

## 6) **Distributed & large‑scale serving**

### 6.1 Parallelisms (combine as needed)

* **Tensor parallelism (TP)**, **Pipeline parallelism (PP)**, **Data parallelism (DP)**, and **Expert parallelism (EP)** for MoE. Tuned via engine/server args. ([VLLM Documentation][13])

### 6.2 Disaggregated prefill/serving

* **Prefill/Decode split**: independently scale prefill vs. decode workers; v0.11 adds connectors (e.g., **NixlConnector**, **P2P NCCL**) and example proxies. Monitor KV‑transfer metrics. ([VLLM Documentation][22])

### 6.3 Dual‑Batch Overlap (DBO)

* Overlap microbatches to raise utilization; thresholds exposed via CLI; kernels explicitly note DBO buffers. ([VLLM Documentation][23])

---

## 7) **Quantization & memory**

Supported methods (device‑dependent) include **GPTQ**, **AWQ**, **FP8 (W8A8)**, **INT8 (W8A8)**, **INT4/W4A16**, **BitBLAS**, **HQQ/Marlin**, and **NVFP4** on Blackwell; **GGUF** is **experimental** and may be incompatible with other features. See the v0.11.0 quantization index and per‑backend pages. ([VLLM Documentation][24])

**Guidance**

* Prefer **FP8** (Hopper+) and **W8A8** where kernels exist; use **GPTQ/AWQ** for weight‑only low‑mem footprints. Validate throughput: some quant paths can be slower if unsupported kernels hit fallbacks. ([GitHub][25])

**KV cache offload to CPU**

* New in this cycle: CPU offloading with LRU management to extend effective context under pressure. ([GitHub][1])

**Sleep mode**

* Release most GPU memory (weights + KV) without stopping the process; wake when traffic returns. CLI toggles and allocator details are documented. ([VLLM Documentation][26])

---

## 8) **Tuning & correctness**

* **Chunked prefill**: size thresholds & concurrency tuning for very long prompts; integrate with prompt logprobs if needed. ([VLLM Documentation][27])
* **Logprobs**: prompt and generated token logprobs are supported, but stability can vary with batching/precision; FAQ calls this out. ([VLLM Documentation][28])
* **Model length & KV sizing**: worker profiles free memory and computes KV capacity; you can override via `--max-model-len` and utilization caps. ([VLLM Documentation][29])
* **Optimization checklists**: preemption metrics, scheduling parameters, and CUDA/HIP graph tips in the optimization guide. ([VLLM Documentation][27])

---

## 9) **Observability & SRE**

* **Metrics**: engine, scheduler, spec‑decode, KV‑transfer all expose counters/gauges; see module‑level docs for names and MP‑safe Prometheus exporters. ([VLLM Documentation][21])
* **Dashboards**: canned Grafana JSON for throughput, TTFT, utilization, KV pressure, queueing, and error rates. ([VLLM Documentation][30])

---

## 10) **Server features matrix (practical)**

| Capability                 | Where / How                                                                                               |
| -------------------------- | --------------------------------------------------------------------------------------------------------- |
| **Chat/Completions**       | `/v1/chat/completions`, `/v1/completions` (OpenAI‑compatible). ([VLLM Documentation][14])                 |
| **Embeddings**             | `/v1/embeddings` + long‑text chunk helpers. ([VLLM Documentation][19])                                    |
| **Tool calling**           | Enable tool parser; choose parser per model family (e.g., Pythonic for Llama). ([VLLM Documentation][16]) |
| **Structured outputs**     | Regex / JSON schema / grammar via `SamplingParams` or OpenAI payload. ([VLLM Documentation][17])          |
| **Classification / Score** | `/v1/classifications` and `/v1/scores` (cross‑encoder or embedding). ([VLLM Documentation][31])           |
| **Transcription**          | Whisper‑style transcription examples. ([VLLM Documentation][20])                                          |
| **LoRA**                   | Load/unload endpoints + per‑request selection; multi‑LoRA pipelining. ([VLLM Documentation][18])          |
| **Metrics**                | `/metrics` (Prometheus). ([VLLM Documentation][21])                                                       |

---

## 11) **CLI & configuration hotspots**

* **`vllm serve` arguments** (JSON/flags) control model, parallelism, schedulers, chunked prefill, prefix caching, LoRA, sleep mode, telemetry, etc. Use the CLI docs to map flags → behavior (e.g., `--tensor-parallel-size`, `--gpu-memory-utilization`, `--enable-chunked-prefill`, `--max-model-len`). ([VLLM Documentation][15])
* **Engine args** apply both to offline (`LLM(...)`) and online (server) modes; keep the set consistent across environments. ([VLLM Documentation][13])
* **Bench / run‑batch** for capacity and regression testing; DBO thresholds are exposed. ([VLLM Documentation][23])

---

## 12) **Secure & robust operations**

* **Hardening**: vLLM exposes an OpenAI‑compatible HTTP API; put it behind an API gateway/reverse proxy with auth/rate‑limits; isolate GPU workers by role (prefill vs. decode). *(Our local architecture fronts multiple vLLM processes with a single HTTP entrypoint.)* 
* **Version guardrails**: be aware of the `--async-scheduling` caveat on v0.11.0; disable until patched. ([GitHub][1])
* **Vuln watch**: track third‑party advisories for deserialization/queue use; review your queue/messaging exposure. ([Vulnerability Info Guide][32])

---

## 13) **Design patterns for best‑in‑class deployments**

1. **One‑process‑per‑base‑model**; use a router to compose multiple models/roles into one endpoint; pin per‑process GPU affinity. 
2. **Hybrid long‑context strategy**: turn on **chunked prefill** + **prefix caching**; enforce prompt templating to maximize cache hits; sample with **spec‑decode** when compatible. ([VLLM Documentation][27])
3. **Multi‑tenant adapters**: serve **multi‑LoRA** on a shared base; hot‑load/unload with **LRU** limits; reject incompatible adapters (e.g., with `lm_head` weights). ([VLLM Documentation][18])
4. **Disaggregated serving** at scale: allocate more prefill replicas for long prompts; wire **NixlConnector** or **P2P NCCL**; monitor KV‑transfer latency and acceptance rates. ([VLLM Documentation][33])
5. **Quantization staging**: start on FP16/BF16, then test FP8/W8A8; finally try GPTQ/AWQ per model with perf/quality gates; avoid experimental **GGUF** in mission‑critical services. ([VLLM Documentation][24])
6. **Observability first**: ingest `/metrics` to Prometheus; import the Grafana JSON; set alerts on queue depth, TTFT, tokens/s, KV usage, OOM/backoffs. ([VLLM Documentation][21])

---

## 14) **Concrete snippets**

### 14.1 OpenAI client against vLLM server

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8000/v1", api_key="not-used")
r = client.chat.completions.create(
  model="meta-llama/Llama-3.1-8B-Instruct",
  messages=[{"role":"user","content":"Write a haiku about KV caches."}],
  temperature=0.3,
)
print(r.choices[0].message.content)
```

Server feature set & endpoints: see OpenAI‑compatible docs. ([VLLM Documentation][14])

### 14.2 Tool calling (pythonic parser for Llama 3.2/4)

```python
from openai import OpenAI
tools=[{"type":"function","function":{"name":"weather","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}}]
client = OpenAI(base_url="http://localhost:8000/v1", api_key="x")
r = client.chat.completions.create(model="meta-llama/Llama-3.2-3B-Instruct",
  messages=[{"role":"user","content":"What's the weather in Kyoto?"}],
  tools=tools, tool_choice="auto", extra_body={"tool_parser":"pythonic"})
print(r.choices[0].message.tool_calls)
```

Parser selection & options: see docs. ([VLLM Documentation][34])

### 14.3 Dynamic LoRA (server‑side)

```bash
curl -X POST http://localhost:8000/v1/load_lora_adapter \
  -H "Content-Type: application/json" \
  -d '{"name":"zephyr_sql","path":"alignment-handbook/zephyr-7b-sft-lora"}'
# ... per-request: {"lora_name":"zephyr_sql"} in the OpenAI payload
```

LoRA endpoints & usage caveats: see docs. ([VLLM Documentation][18])

---

## 15) **API surfaces you’ll use most**

* **Python**: `vllm.LLM`, `SamplingParams`, `LLM.generate/stream/embed/classify/score`; async helpers; explicit examples for DP/torchrun. ([VLLM Documentation][8])
* **Server**: `vllm serve` (JSON/flags), OpenAI endpoints, **tool parser**, **response_format/structured outputs**, **metrics**. ([VLLM Documentation][15])
* **Config**: Engine args (TP/PP/DP/EP, cache, schedulers, prefill thresholds), model config knobs, quantization selections. ([VLLM Documentation][13])

---

## 16) **Footguns & guardrails**

* **Disable `--async-scheduling`** on v0.11.0 until the fix lands. ([GitHub][1])
* **GGUF is experimental**—expect incompatibilities/perf gaps vs. native HF checkpoints. ([VLLM Documentation][35])
* **Quantization perf ≠ guaranteed**: validate GPTQ/AWQ paths per GPU/kernel; fallback can be slower than fp16. ([GitHub][25])
* **Logprob determinism**: not guaranteed under batching/graphing; compare within tolerances. ([VLLM Documentation][36])

---

## 17) **Checklists for an autonomous agent**

**Bring‑up**

* [ ] Select model(s), context window, and quantization target.
* [ ] Decide parallelism plan (TP/PP/DP/EP) + #GPUs per role.
* [ ] Start `vllm serve` with **chunked prefill**, **prefix caching**, **metrics**, **tool parser** (if needed). ([VLLM Documentation][27])

**Perf**

* [ ] Size KV budget from worker profiling; set `--max-model-len` and cache ratios. ([VLLM Documentation][29])
* [ ] Enable **DBO**; tune thresholds; verify tokens/s. ([VLLM Documentation][23])
* [ ] If long prompts dominate, pilot **disaggregated prefill** with Nixl or P2P. ([VLLM Documentation][22])

**Functionality**

* [ ] For RAG/routing, enable **Score** API and embeddings. ([VLLM Documentation][37])
* [ ] For tools/agents, pick the right **tool parser** and **structured outputs** backend. ([VLLM Documentation][34])
* [ ] For multi‑tenant, set **LoRA** limits and hot‑load policies. ([VLLM Documentation][18])

**SRE**

* [ ] Scrape `/metrics`; import Grafana dashboards; alert on TTFT, queue depth, KV utilization, OOM. ([VLLM Documentation][21])
* [ ] Periodic **bench** (`vllm bench`) for latency/throughput regressions. ([VLLM Documentation][23])
* [ ] Use **sleep mode** for low‑traffic windows to cut GPU cost. ([VLLM Documentation][26])

---

## 18) **Authoritative references (pin these when you implement)**

* **v0.11.0 Release notes (breaking changes, model/feature deltas, quant, scheduling)**. ([GitHub][1])
* **OpenAI‑compatible server docs** (endpoints, payloads, extras). ([VLLM Documentation][14])
* **PagedAttention design** (and original paper). ([VLLM Documentation][3])
* **Quantization index** (per‑backend guidance; GGUF warning). ([VLLM Documentation][24])
* **Structured outputs** (regex/JSON/grammar) and **tool calling** (parsers). ([VLLM Documentation][17])
* **Disaggregated serving & connectors** (Nixl, P2P NCCL) and **DBO** knobs. ([VLLM Documentation][22])
* **Metrics & dashboards** (Prometheus/Grafana). ([VLLM Documentation][21])
* **CUDA 13 baseline container** (driver/toolchain guidance). ([NVIDIA Docs][2])
* **Architecture mapping (single endpoint ⇢ multiple vLLM processes)**. 

---

### Appendix A — Minimal “golden” examples for CI

**1) Offline generate + logprobs sanity**

```python
from vllm import LLM, SamplingParams
llm = LLM("Qwen/Qwen2.5-7B-Instruct")
sp  = SamplingParams(temperature=0.0, max_tokens=32, logprobs=5, prompt_logprobs=5)
o   = llm.generate(["Test prompt"], sp)[0]
assert o.outputs[0].text and o.prompt_logprobs is not None
```

API references: `SamplingParams`, `outputs` schema. ([VLLM Documentation][8])

**2) OpenAI server tool calling + structured output (JSON)**

* Start: `vllm serve --model meta-llama/Llama-3.2-3B-Instruct --tool-parser pythonic`
* Client: send `tools=[...]`, `tool_choice="auto"`, `response_format={"type":"json_object"}`. ([VLLM Documentation][34])

**3) Disaggregated serving smoke**

* Run the example proxy & split workers (XpYd); ensure KV‑transfer metrics increment and E2E latency falls under long‑prefill load. ([VLLM Documentation][22])

---

If you want, I can tailor a **deployment blueprint** for your hardware (cards, drivers, parallelism plan, router, LoRA policy, autoscaling, dashboards) and produce a **ready‑to‑run config + compose** set that mirrors this guidance and your existing single‑box architecture. 

[1]: https://github.com/vllm-project/vllm/releases "Releases · vllm-project/vllm · GitHub"
[2]: https://docs.nvidia.com/deeplearning/frameworks/vllm-release-notes/rel-25-09.html?utm_source=chatgpt.com "vLLM Release 25.09"
[3]: https://docs.vllm.ai/en/latest/design/paged_attention.html?utm_source=chatgpt.com "Paged Attention - vLLM"
[4]: https://docs.vllm.ai/en/stable/examples/offline_inference/batch_llm_inference.html?utm_source=chatgpt.com "Batch LLM Inference - vLLM"
[5]: https://docs.vllm.ai/en/v0.11.0/examples/offline_inference/prefix_caching.html?utm_source=chatgpt.com "Prefix Caching - vLLM"
[6]: https://docs.vllm.ai/en/v0.11.0/getting_started/installation/gpu.html?utm_source=chatgpt.com "GPU - vLLM"
[7]: https://pypi.org/project/vllm/?utm_source=chatgpt.com "vllm"
[8]: https://docs.vllm.ai/en/v0.11.0/api/vllm/sampling_params.html?utm_source=chatgpt.com "sampling_params - vLLM"
[9]: https://docs.vllm.ai/en/v0.11.0/examples/offline_inference/async_llm_streaming.html?utm_source=chatgpt.com "Async LLM Streaming - vLLM"
[10]: https://docs.vllm.ai/en/v0.11.0/models/pooling_models.html?utm_source=chatgpt.com "Pooling Models - vLLM"
[11]: https://docs.vllm.ai/en/v0.11.0/features/spec_decode.html?utm_source=chatgpt.com "Speculative Decoding - vLLM"
[12]: https://docs.vllm.ai/en/v0.11.0/features/multimodal_inputs.html?utm_source=chatgpt.com "Multimodal Inputs - vLLM"
[13]: https://docs.vllm.ai/en/v0.11.0/configuration/engine_args.html?utm_source=chatgpt.com "Engine Arguments - vLLM"
[14]: https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html?utm_source=chatgpt.com "OpenAI-Compatible Server - vLLM"
[15]: https://docs.vllm.ai/en/v0.11.0/cli/serve.html?utm_source=chatgpt.com "JSON CLI Arguments - vLLM"
[16]: https://docs.vllm.ai/en/v0.11.0/features/tool_calling.html?utm_source=chatgpt.com "Tool Calling - vLLM"
[17]: https://docs.vllm.ai/en/v0.11.0/usage/structured_outputs.html?utm_source=chatgpt.com "Structured Outputs - vLLM"
[18]: https://docs.vllm.ai/en/latest/features/lora.html?utm_source=chatgpt.com "LoRA Adapters - vLLM"
[19]: https://docs.vllm.ai/en/v0.11.0/examples/online_serving/openai_embedding_long_text.html?utm_source=chatgpt.com "Long Text Embedding with Chunked Processing - vLLM"
[20]: https://docs.vllm.ai/en/v0.11.0/examples/online_serving/openai_transcription_client.html?utm_source=chatgpt.com "OpenAI Transcription Client - vLLM"
[21]: https://docs.vllm.ai/en/v0.11.0/usage/metrics.html?utm_source=chatgpt.com "Production Metrics - vLLM"
[22]: https://docs.vllm.ai/en/v0.11.0/examples/online_serving/disaggregated_serving.html?utm_source=chatgpt.com "Disaggregated Serving - vLLM"
[23]: https://docs.vllm.ai/en/v0.11.0/cli/run-batch.html?utm_source=chatgpt.com "vllm run-batch"
[24]: https://docs.vllm.ai/en/v0.11.0/features/quantization/index.html?utm_source=chatgpt.com "Quantization - vLLM"
[25]: https://github.com/vllm-project/vllm/issues/4359?utm_source=chatgpt.com "[Feature]: GPTQ/AWQ quantization is not fully optimized yet ..."
[26]: https://docs.vllm.ai/en/v0.11.0/features/sleep_mode.html?utm_source=chatgpt.com "Sleep Mode - vLLM"
[27]: https://docs.vllm.ai/en/v0.11.0/configuration/optimization.html?utm_source=chatgpt.com "Optimization and Tuning - vLLM"
[28]: https://docs.vllm.ai/en/v0.11.0/api/vllm/v1/engine/logprobs.html?utm_source=chatgpt.com "logprobs - vLLM"
[29]: https://docs.vllm.ai/en/v0.11.0/api/vllm/v1/worker/gpu_worker.html?utm_source=chatgpt.com "gpu_worker - vLLM"
[30]: https://docs.vllm.ai/en/v0.11.0/examples/online_serving/dashboards.html?utm_source=chatgpt.com "Monitoring Dashboards - vLLM"
[31]: https://docs.vllm.ai/en/v0.11.0/api/vllm/entrypoints/openai/serving_classification.html?utm_source=chatgpt.com "serving_classification - vLLM"
[32]: https://security.snyk.io/package/pip/vllm/0.11.0?utm_source=chatgpt.com "vllm 0.11.0 vulnerabilities"
[33]: https://docs.vllm.ai/en/v0.11.0/features/nixl_connector_usage.html?utm_source=chatgpt.com "NixlConnector Usage Guide - vLLM"
[34]: https://docs.vllm.ai/en/v0.11.0/api/vllm/entrypoints/openai/tool_parsers/pythonic_tool_parser.html?utm_source=chatgpt.com "pythonic_tool_parser - vLLM"
[35]: https://docs.vllm.ai/en/stable/features/quantization/gguf.html?utm_source=chatgpt.com "GGUF - vLLM"
[36]: https://docs.vllm.ai/en/v0.11.0/usage/faq.html?utm_source=chatgpt.com "Frequently Asked Questions - vLLM"
[37]: https://docs.vllm.ai/en/v0.11.0/api/vllm/entrypoints/openai/serving_score.html?utm_source=chatgpt.com "serving_score - vLLM"
