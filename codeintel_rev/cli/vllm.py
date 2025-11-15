"""Standalone helpers for managing a local vLLM HTTP server.

Usage:
    python -m codeintel_rev.cli.vllm serve-http --model /path/to/model
    python -m codeintel_rev.cli.vllm shutdown
"""

from __future__ import annotations

import argparse
import os
import shlex
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8001
DEFAULT_MODEL = "nomic-ai/nomic-embed-code"
DEFAULT_PID_FILE = Path(os.environ.get("VLLM_PID_FILE", "/tmp/vllm-http.pid"))
DEFAULT_BASE_URL = "http://127.0.0.1:8001/v1"
DEFAULT_HF_CACHE = Path(
    os.environ.get("HF_HOME")
    or os.environ.get("HUGGINGFACE_HUB_CACHE")
    or "/home/paul/.cache/huggingface"
)


def _infer_host_port(base_url: str) -> tuple[str, int]:
    if "://" not in base_url:
        raise ValueError(f"Invalid base URL: {base_url}")
    _, rest = base_url.split("://", 1)
    host_port = rest.split("/", 1)[0]
    if ":" in host_port:
        host, port_s = host_port.split(":", 1)
        return host, int(port_s)
    return host_port, DEFAULT_PORT


def _health_url(base_url: str) -> str:
    if base_url.rstrip("/").endswith("/v1"):
        return base_url.rstrip("/") + "/health"
    return base_url.rstrip("/") + "/v1/health"


def _build_server_argv(
    *,
    model: str,
    host: str,
    port: int,
    served_model_name: str | None,
    tensor_parallel_size: int | None,
    gpu_memory_utilization: float | None,
    max_num_batched_tokens: int | None,
) -> list[str]:
    argv = [
        sys.executable,
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model",
        model,
        "--host",
        host,
        "--port",
        str(port),
        "--task",
        "embed",
        "--trust-remote-code",
    ]
    if tensor_parallel_size and tensor_parallel_size > 1:
        argv += ["--tensor-parallel-size", str(tensor_parallel_size)]
    if gpu_memory_utilization:
        argv += ["--gpu-memory-utilization", str(gpu_memory_utilization)]
    if max_num_batched_tokens:
        argv += ["--max-num-batched-tokens", str(max_num_batched_tokens)]
    if served_model_name:
        argv += ["--served-model-name", served_model_name]
    return argv


def _env_for_cache(cache_root: Path, offline: bool) -> dict[str, str]:
    env = os.environ.copy()
    env["HF_HOME"] = str(cache_root)
    env["HUGGINGFACE_HUB_CACHE"] = str(cache_root)
    if offline:
        env["HF_HUB_OFFLINE"] = "1"
    env.setdefault("VLLM_USE_FLASHINFER", "1")
    return env


def _wait_until_ready(base_url: str, timeout_s: float) -> None:
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - runtime guard
        raise RuntimeError("httpx is required for readiness checks (pip install httpx).") from exc
    url = _health_url(base_url)
    deadline = time.time() + timeout_s
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            resp = httpx.get(url, timeout=5.0)
            if resp.status_code == 200:
                return
        except Exception as exc:
            last_err = exc
        time.sleep(0.5)
    raise TimeoutError(f"Server did not become healthy at {url}: {last_err}")


def cmd_serve_http(args: argparse.Namespace) -> int:
    base_url = args.base_url or DEFAULT_BASE_URL
    host, port = _infer_host_port(base_url)
    model = args.model or DEFAULT_MODEL
    cache_root = Path(args.hf_cache or DEFAULT_HF_CACHE)
    cache_root.mkdir(parents=True, exist_ok=True)

    argv = _build_server_argv(
        model=model,
        host=host,
        port=port,
        served_model_name=args.served_model_name or DEFAULT_MODEL,
        tensor_parallel_size=args.tensor_parallel_size,
        gpu_memory_utilization=args.gpu_memory_utilization,
        max_num_batched_tokens=args.max_num_batched_tokens,
    )
    env = _env_for_cache(cache_root, not args.online)

    if args.print_cmd:
        print("[serve-http] Launching:", " ".join(shlex.quote(x) for x in argv), file=sys.stderr)

    proc = subprocess.Popen(argv, env=env, start_new_session=True)
    args.pid_file.parent.mkdir(parents=True, exist_ok=True)
    args.pid_file.write_text(str(proc.pid), encoding="utf-8")
    print(f"[serve-http] PID {proc.pid} -> {base_url}", file=sys.stderr)

    if not args.no_wait:
        _wait_until_ready(base_url, args.timeout)
        print("[serve-http] Ready", file=sys.stderr)

    return 0


def _wait_for_exit(pid: int, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.25)
    return False


def cmd_shutdown(args: argparse.Namespace) -> int:
    if not args.pid_file.exists():
        print(f"[shutdown] PID file not found: {args.pid_file}", file=sys.stderr)
        return 1
    try:
        pid = int(args.pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError) as exc:
        print(f"[shutdown] Failed to read PID file: {exc}", file=sys.stderr)
        return 1

    print(f"[shutdown] Sending SIGTERM to {pid}", file=sys.stderr)
    with suppress(ProcessLookupError):
        os.kill(pid, signal.SIGTERM)
    stopped = _wait_for_exit(pid, args.timeout)
    if not stopped and args.force:
        print("[shutdown] Forcing SIGKILL", file=sys.stderr)
        with suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
        stopped = _wait_for_exit(pid, args.timeout / 2)

    if not stopped:
        print("[shutdown] Process did not exit; use --force to send SIGKILL.", file=sys.stderr)
        return 1

    args.pid_file.unlink(missing_ok=True)
    print("[shutdown] Server stopped", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="vLLM HTTP server helper.")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve-http", help="Launch OpenAI-compatible vLLM server.")
    serve.add_argument("--model", type=str, default=None, help="HF repo or local path.")
    serve.add_argument(
        "--served-model-name", type=str, default=None, help="Model name clients send."
    )
    serve.add_argument("--base-url", type=str, default=DEFAULT_BASE_URL)
    serve.add_argument("--host", type=str, default=None, help="Override host binding.")
    serve.add_argument("--port", type=int, default=None, help="Override port binding.")
    serve.add_argument("--hf-cache", type=str, default=None, help="HF cache root.")
    serve.add_argument("--online", action="store_true", help="Allow HF downloads.")
    serve.add_argument("--tensor-parallel-size", type=int, default=None)
    serve.add_argument("--gpu-memory-utilization", type=float, default=0.6)
    serve.add_argument("--max-num-batched-tokens", type=int, default=4096)
    serve.add_argument("--pid-file", type=Path, default=DEFAULT_PID_FILE)
    serve.add_argument("--timeout", type=float, default=60.0, help="Seconds to wait for readiness.")
    serve.add_argument("--print-cmd", action="store_true", help="Echo server command.")
    serve.add_argument("--no-wait", action="store_true", help="Do not block for readiness.")
    serve.set_defaults(func=cmd_serve_http)

    shut = sub.add_parser("shutdown", help="Stop the running vLLM server.")
    shut.add_argument("--pid-file", type=Path, default=DEFAULT_PID_FILE)
    shut.add_argument("--timeout", type=float, default=10.0)
    shut.add_argument("--force", action="store_true", help="Send SIGKILL if needed.")
    shut.set_defaults(func=cmd_shutdown)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
