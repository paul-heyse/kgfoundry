# Embedding Service

The `codeintel_rev.embeddings` module centralises how the stack produces dense
vectors. It exposes a single `EmbeddingProvider` abstraction backed either by
the in-process vLLM engine or a Hugging Face fallback and is consumed by CLI
tools (`indexctl embeddings …`) and the indexing pipeline.

## Configuration

`EmbeddingsConfig` (see `config/settings.py`) is the canonical source of truth
for provider selection and batching. The most relevant environment variables
are:

| Variable | Purpose | Default |
| --- | --- | --- |
| `EMBED_PROVIDER` | `"vllm"` (GPU) or `"hf"` (CPU fallback) | `vllm` |
| `EMBED_MODEL` | Model identifier | `nomic-ai/nomic-embed-code` |
| `EMBED_DEVICE` | `"auto"`, `"cuda"`, or `"cpu"` | `auto` |
| `EMBED_BATCH_SIZE` | Logical batch size requested by callers | `64` |
| `EMBED_MICRO_BATCH_SIZE` | Internal micro-batch size for the bounded executor | `min(batch_size/2, 64)` |
| `EMBED_MAX_TOKENS` | Sequence guard passed to tokenisers | `4096` |
| `EMBED_ALLOW_HF_FALLBACK` | Enable automatic HF fallback when vLLM init fails | `true` |

## Operator note: choosing batch sizes

The bounded executor coalesces pending requests into *micro-batches* to keep
GPU utilisation high while remaining responsive for small jobs.

- **Small corpora (≤ 10k chunks)** — set `--chunk-size`/`EMBED_BATCH_SIZE` to
  **256**. This keeps memory usage low and shortens turn-around for rebuilds.
- **Medium corpora (10k–100k chunks)** — set the batch size to **512** and the
  micro-batch to **64**. This saturates a single A100/4090 while staying within
  ~10 GB of VRAM. Increase only if monitoring shows GPU headroom.

For CPU-only hosts stick with the default micro-batch of 32; the HF fallback
will auto-detect whether `torch.cuda` is available and normalise vectors
identically to the GPU path.

## CLI workflow

1. `indexctl embeddings build` — reads chunks from `catalog.duckdb`, embeds them
   in batches and writes both `embeddings.parquet` and a manifest containing
   `{model, dim, dtype, provider, checksum}`. When invoked inside an index
   version directory it also writes `embedding_meta.json` next to the other
   lifecycle assets.
2. `indexctl embeddings validate` — samples existing vectors, recomputes them
   via the current provider, and highlights cosine drift above the configured
   epsilon.

Both commands honour the same embedding configuration and log throughput,
tokens/sec, and per-device metrics.
