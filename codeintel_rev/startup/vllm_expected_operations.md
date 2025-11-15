You're right—the repo expects a *running* vLLM service, but there’s no “bring‑up” script. Below is a drop‑in CLI that follows your existing Typer/`cli_operation(...)` pattern and the configuration conventions already used across the project (env‑driven `load_settings()`, `VLLM_URL`, `VLLM_MODEL`, etc.). It starts the **OpenAI‑compatible vLLM server** in **embedding** mode, points it at your local HF cache, and blocks until the repo’s **readiness probe** (`GET {base_url}/health`) succeeds—exactly what your code expects when `VLLM run=HTTP` is configured. The examples use your model `nomic-ai/nomic-embed-code` and default base URL style `http://127.0.0.1:8001/v1`.

---

## 1) New CLI: `codeintel_rev/cli/vllm.py`

> **What this does**
>
> * Reads model / base URL defaults from the same settings entry points you already use (`load_settings()` + env like `VLLM_URL`, `VLLM_MODEL`). 
> * Spawns `python -m vllm.entrypoints.openai.api_server` in **embedding** mode.
> * Sets `HF_HUB_OFFLINE=1` and points `HUGGINGFACE_HUB_CACHE` (and `HF_HOME`) at your local cache root (`/home/paul/.cache/huggingface`) so it will serve from disk without network.
> * Waits on `GET /health` under your configured `base_url` (`…/v1/health`) before returning. Your repo’s readiness probe already checks this endpoint. 

Create **`codeintel_rev/cli/vllm.py`**:

```python
# SPDX-License-Identifier: MIT
# codeintel_rev/cli/vllm.py
from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple
import typer

try:
    import httpx
except ImportError:
    httpx = None  # defer import error to runtime

from codeintel_rev.config.settings import load_settings  # env-driven settings loader
from codeintel_rev.cli.bm25 import cli_operation, CliContext, EnvelopeBuilder  # local CLI pattern

app = typer.Typer(help="Start a vLLM OpenAI-compatible embedding server (HTTP).")

DEFAULT_HF_CACHE = Path(os.environ.get("HF_HOME") or os.environ.get("HUGGINGFACE_HUB_CACHE") or "/home/paul/.cache/huggingface")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8001

def _infer_host_port(base_url: str) -> Tuple[str, int]:
    # Accept styles like http://127.0.0.1:8001/v1  (your docs/examples use /v1)  # noqa
    # We avoid urlparse to keep dependencies light.
    if "://" not in base_url:
        raise ValueError(f"Invalid VLLM_URL: {base_url}")
    _, rest = base_url.split("://", 1)
    host_port = rest.split("/", 1)[0]
    if ":" in host_port:
        host, port_s = host_port.split(":", 1)
        return host, int(port_s)
    return host_port, DEFAULT_PORT

def _health_url(base_url: str) -> str:
    # repo readiness probe expects GET {base_url}/health  (e.g., http://127.0.0.1:8001/v1/health)
    # Matches your ReadinessProbe._check_vllm_http() doc.  # noqa
    path = "/health" if base_url.endswith("/v1") else "/v1/health"
    # Defensive: if user passes trailing slash etc.
    if base_url.rstrip("/").endswith("/v1"):
        return base_url.rstrip("/") + "/health"
    return base_url.rstrip("/") + "/v1/health"

def _build_server_argv(
    *,
    model: str,
    host: str,
    port: int,
    tensor_parallel_size: int | None,
    gpu_memory_utilization: float | None,
    max_num_batched_tokens: int | None,
    served_model_name: Optional[str] = None,
) -> list[str]:
    argv = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--model", model,
        "--host", host,
        "--port", str(port),
        "--task", "embedding",
        "--dtype", "auto",
    ]
    if tensor_parallel_size and tensor_parallel_size > 1:
        argv += ["--tensor-parallel-size", str(tensor_parallel_size)]
    if gpu_memory_utilization:
        argv += ["--gpu-memory-utilization", str(gpu_memory_utilization)]
    if max_num_batched_tokens:
        argv += ["--max-num-batched-tokens", str(max_num_batched_tokens)]
    # Make sure the model name that clients send matches server side
    if served_model_name:
        argv += ["--served-model-name", served_model_name]
    return argv

def _env_for_hf_cache(cache_root: Path, offline: bool) -> dict[str, str]:
    env = os.environ.copy()
    # vLLM honors both; set both for clarity.
    env["HF_HOME"] = str(cache_root)
    env["HUGGINGFACE_HUB_CACHE"] = str(cache_root)
    if offline:
        env["HF_HUB_OFFLINE"] = "1"
    return env

def _wait_until_ready(base_url: str, timeout_s: float = 120.0, interval_s: float = 0.5) -> None:
    if httpx is None:
        raise RuntimeError("httpx is required for readiness checks. pip install httpx")
    url = _health_url(base_url)
    deadline = time.time() + timeout_s
    last_err: Optional[Exception] = None
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=10.0)
            if r.status_code == 200:
                return
        except Exception as e:
            last_err = e
        time.sleep(interval_s)
    raise TimeoutError(f"vLLM server did not become healthy at {url} in {timeout_s}s. Last error: {last_err!r}")

@app.command("serve")
@cli_operation(echo_args=True, echo_env=True)
def serve(
    ctx: CliContext,
    env: EnvelopeBuilder,
    *,
    # Defaults flow from repo settings (VLLM_URL, VLLM_MODEL, etc.)
    model: Optional[str] = typer.Option(None, help="HF repo id or local dir (e.g., 'nomic-ai/nomic-embed-code')."),
    base_url: Optional[str] = typer.Option(None, help="Base URL clients will use, e.g. http://127.0.0.1:8001/v1"),
    host: Optional[str] = typer.Option(None, help="Override listen host (default derived from base_url)."),
    port: Optional[int] = typer.Option(None, help="Override listen port (default derived from base_url)."),
    hf_cache: Path = typer.Option(DEFAULT_HF_CACHE, exists=False, help="HF cache root (parent of 'hub/')"),
    offline: bool = typer.Option(True, help="Set HF_HUB_OFFLINE=1."),
    tensor_parallel_size: Optional[int] = typer.Option(None, help="--tensor-parallel-size"),
    gpu_memory_utilization: Optional[float] = typer.Option(0.9, help="--gpu-memory-utilization"),
    max_num_batched_tokens: Optional[int] = typer.Option(65536, help="--max-num-batched-tokens"),
    served_model_name: Optional[str] = typer.Option(None, help="Force served model name (clients send this)."),
    no_wait: bool = typer.Option(False, help="Do not block for /health readiness."),
    print_cmd: bool = typer.Option(True, help="Echo the vLLM server command line."),
) -> None:
    """
    Start vLLM OpenAI-compatible server in **embedding** mode and wait for /health.

    The rest of the codebase expects an HTTP vLLM endpoint at a base URL like
    `http://127.0.0.1:8001/v1` and probes `GET /health` for readiness.  # see ReadinessProbe docs
    """

    settings = load_settings()  # pulls VLLM_URL, VLLM_MODEL, etc. from env
    # Resolve base_url/model from settings if not provided
    model = model or settings.vllm.model
    base_url = base_url or settings.vllm.base_url
    # Derive host/port from base_url unless explicitly overridden
    h, p = _infer_host_port(base_url)
    host = host or h
    port = port or p

    # Ensure HF cache root exists
    hf_cache.mkdir(parents=True, exist_ok=True)

    argv = _build_server_argv(
        model=model,
        host=host,
        port=port,
        tensor_parallel_size=tensor_parallel_size,
        gpu_memory_utilization=gpu_memory_utilization,
        max_num_batched_tokens=max_num_batched_tokens,
        served_model_name=served_model_name or model,
    )
    env_vars = _env_for_hf_cache(hf_cache, offline)

    if print_cmd:
        typer.echo("Launching vLLM:", err=True)
        typer.echo("  " + " ".join(shlex.quote(x) for x in argv), err=True)
        typer.echo(f"  HF cache: {hf_cache}", err=True)
        typer.echo(f"  Base URL: {base_url}", err=True)

    proc = subprocess.Popen(argv, env=env_vars, start_new_session=True)

    # Graceful shutdown on Ctrl-C
    def _term_handler(signum, frame):
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            pass
    signal.signal(signal.SIGINT, _term_handler)
    signal.signal(signal.SIGTERM, _term_handler)

    if not no_wait:
        _wait_until_ready(base_url=base_url, timeout_s=settings.vllm.timeout_s)

    # Keep foreground process attached to child
    proc.wait()
```

**Why this fits the repo:**

* The CLI plugs into your **Typer**-based umbrella CLI via the same lazy‑load pattern as `bm25`, `splade`, `indexctl`, etc. 
* It *resolves defaults* using the same env‑driven loader (`load_settings()` → `VLLM_URL`, `VLLM_MODEL`, *embedding dim, batch size, timeout* docs), so there’s no new config surface to learn. 
* The health wait logic matches your **ReadinessProbe** expectation to call `GET {base_url}/health` (e.g., `http://127.0.0.1:8001/v1/health`). 

---

## 2) Register the CLI under your umbrella app

Append a stanza like your existing ones in **`codeintel_rev/cli/__init__.py`** so `codeintel vllm …` works:

```python
# codeintel_rev/cli/__init__.py  (snippet)
from . import _load_cli_module, app  # existing

vllm_cli = _load_cli_module("codeintel_rev.cli.vllm")  # NEW

# ... later, after other .command() registrations:
app.add_typer(vllm_cli.app, name="vllm")
```

Your aggregator already lazy‑imports sub‑CLIs this way. 

---

## 3) Start commands (using your local HF cache + model)

> You said the model is already in:
> `/home/paul/.cache/huggingface/hub/models--nomic-ai--nomic-embed-code`

Two options:

**A. Serve by repo id (preferred; uses the cache but keeps a clean flag set):**

```bash
export VLLM_URL="http://127.0.0.1:8001/v1"        # matches repo default style
export VLLM_MODEL="nomic-ai/nomic-embed-code"     # default in your settings loader
export HF_HOME="/home/paul/.cache/huggingface"
export HF_HUB_OFFLINE=1

python -m codeintel_rev.cli vllm serve
```

**B. Serve from the local model directory path explicitly (equivalent):**

```bash
export VLLM_URL="http://127.0.0.1:8001/v1"
export HF_HOME="/home/paul/.cache/huggingface"
export HF_HUB_OFFLINE=1

python -m codeintel_rev.cli vllm serve --model "/home/paul/.cache/huggingface/hub/models--nomic-ai--nomic-embed-code"
```

> The base URL style with `/v1` and the readiness probe against `/health` are exactly what your code documents/uses. 

---

## 4) Quick verification (mirrors your client’s expectations)

* **Health**:

  ```bash
  curl -sS http://127.0.0.1:8001/v1/health
  ```

  Your readiness logic assumes `200 OK` on this path. 

* **Embeddings** (server is OpenAI‑compatible; your HTTP client posts to `/v1/embeddings` with `{"model": "...", "input": [...]}`):

  ```bash
  curl -sS http://127.0.0.1:8001/v1/embeddings \
    -H 'Content-Type: application/json' \
    -d '{"model":"nomic-ai/nomic-embed-code","input":["def foo(): pass"]}' | jq .
  ```

  Your in‑repo HTTP client is built around the OpenAI‑style `/v1/embeddings` endpoint and sends the `model` name—matching what we set with `--served-model-name`. 

---

## 5) Notes on defaults & alignment

* **Defaults come from your settings loader**:
  `VLLM_URL` defaults to `http://127.0.0.1:8001/v1`, `VLLM_MODEL` defaults to `nomic-ai/nomic-embed-code`, `VLLM_BATCH_SIZE` to `64`, `VLLM_TIMEOUT_S` to `120.0`, `VLLM_EMBED_DIM` to `3584` per the doc comments—so the rest of the stack (FAISS, dimensions, etc.) stays consistent. 

* **Readiness & health**:
  The CLI waits for `/health` under `base_url` because your `ReadinessProbe` is written to validate an HTTP vLLM endpoint that way (example base URL in the docs is `http://localhost:8001/v1`). 

* **Client compatibility**:
  Your `VLLMClient` performs HTTP POST to the OpenAI‑style embeddings endpoint; this server exposes the same path and JSON shape. 

---

## 6) (Optional) Systemd unit

If you want it to run at boot:

```
# /etc/systemd/system/vllm-embed.service
[Unit]
Description=vLLM Embedding Server (nomic-ai/nomic-embed-code)
After=network-online.target

[Service]
Type=simple
User=paul
Environment=VLLM_URL=http://127.0.0.1:8001/v1
Environment=VLLM_MODEL=nomic-ai/nomic-embed-code
Environment=HF_HOME=/home/paul/.cache/huggingface
Environment=HF_HUB_OFFLINE=1
ExecStart=/usr/bin/python3 -m codeintel_rev.cli vllm serve
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vllm-embed.service
```

---

### Where this ties into the rest of the pipeline

Once this service is up:

* Your **embedding provider** code will call the HTTP client to obtain vectors (OpenAI‑style). 
* `ReadinessProbe` will pass the vLLM check (`/health`). 
* Downstream components (DuckDB + FAISS) already assume the **embedding dimension** and **batch sizes** exposed by settings and used in the client. 

If you want, I can also wire a `codeintel_rev/bin/start_vllm.sh` one‑liner wrapper, but the CLI above keeps everything consistent with your Typer‑based tooling.
