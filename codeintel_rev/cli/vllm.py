"""Standalone helpers for managing a local vLLM HTTP server.

Usage:
    python -m codeintel_rev.cli.vllm serve-http --model /path/to/model
    python -m codeintel_rev.cli.vllm shutdown
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import tempfile
import time
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from kgfoundry_common.subprocess_utils import spawn_background_process

try:
    import httpx
except ImportError:
    httpx = None

DEFAULT_HOST: Final[str] = "127.0.0.1"
DEFAULT_PORT: Final[int] = 8001
DEFAULT_MODEL: Final[str] = "nomic-ai/nomic-embed-code"
DEFAULT_PID_FILE: Final[Path] = Path(
    os.environ.get("VLLM_PID_FILE") or Path(tempfile.gettempdir()) / "vllm-http.pid"
)
DEFAULT_BASE_URL: Final[str] = "http://127.0.0.1:8001/v1"
DEFAULT_HF_CACHE: Final[Path] = Path(
    os.environ.get("HF_HOME")
    or os.environ.get("HUGGINGFACE_HUB_CACHE")
    or (Path.home() / ".cache" / "huggingface")
)
HTTP_OK: Final[int] = 200


@dataclass(slots=True, frozen=True)
class ServerLaunchOptions:
    """Configuration for launching a vLLM HTTP server."""

    model: str
    host: str
    port: int
    served_model_name: str | None
    tensor_parallel_size: int | None
    gpu_memory_utilization: float | None
    max_num_batched_tokens: int | None


def _infer_host_port(base_url: str) -> tuple[str, int]:
    if "://" not in base_url:
        msg = f"Invalid base URL: {base_url}"
        raise ValueError(msg)
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


def _build_server_argv(options: ServerLaunchOptions) -> list[str]:
    argv = [
        sys.executable,
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model",
        options.model,
        "--host",
        options.host,
        "--port",
        str(options.port),
        "--task",
        "embed",
        "--trust-remote-code",
    ]
    if options.tensor_parallel_size and options.tensor_parallel_size > 1:
        argv += ["--tensor-parallel-size", str(options.tensor_parallel_size)]
    if options.gpu_memory_utilization:
        argv += ["--gpu-memory-utilization", str(options.gpu_memory_utilization)]
    if options.max_num_batched_tokens:
        argv += ["--max-num-batched-tokens", str(options.max_num_batched_tokens)]
    if options.served_model_name:
        argv += ["--served-model-name", options.served_model_name]
    return argv


def _env_for_cache(cache_root: Path, *, offline: bool) -> dict[str, str]:
    env = os.environ.copy()
    env["HF_HOME"] = str(cache_root)
    env["HUGGINGFACE_HUB_CACHE"] = str(cache_root)
    if offline:
        env["HF_HUB_OFFLINE"] = "1"
    env.setdefault("VLLM_USE_FLASHINFER", "1")
    return env


def _wait_until_ready(base_url: str, timeout_s: float) -> None:
    if httpx is None:  # pragma: no cover - dependency guard
        msg = "httpx is required for readiness checks (pip install httpx)."
        raise RuntimeError(msg)
    url = _health_url(base_url)
    deadline = time.time() + timeout_s
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            resp = httpx.get(url, timeout=5.0)
            if resp.status_code == HTTP_OK:
                return
        except (httpx.HTTPError, OSError) as exc:
            last_err = exc
        time.sleep(0.5)
    msg = f"Server did not become healthy at {url}: {last_err}"
    raise TimeoutError(msg)


def cmd_serve_http(args: argparse.Namespace) -> int:
    """Launch and manage a vLLM HTTP server process.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments containing model configuration, server
        binding options, and process management settings.

    Returns
    -------
    int
        Exit code: 0 on success, non-zero on failure. The function launches
        the server as a subprocess and optionally waits for it to become
        healthy before returning.
    """
    configured_base = args.base_url or DEFAULT_BASE_URL
    inferred_host, inferred_port = _infer_host_port(configured_base)
    host = args.host or inferred_host
    port = args.port or inferred_port
    base_url = configured_base if args.base_url else f"http://{host}:{port}/v1"
    model = args.model or DEFAULT_MODEL
    cache_root = Path(args.hf_cache or DEFAULT_HF_CACHE)
    cache_root.mkdir(parents=True, exist_ok=True)

    options = ServerLaunchOptions(
        model=model,
        host=host,
        port=port,
        served_model_name=args.served_model_name or DEFAULT_MODEL,
        tensor_parallel_size=args.tensor_parallel_size,
        gpu_memory_utilization=args.gpu_memory_utilization,
        max_num_batched_tokens=args.max_num_batched_tokens,
    )
    argv = _build_server_argv(options)
    env = _env_for_cache(cache_root, offline=not args.online)

    proc = spawn_background_process(argv, env=env, start_new_session=True)
    args.pid_file.parent.mkdir(parents=True, exist_ok=True)
    args.pid_file.write_text(str(proc.pid), encoding="utf-8")
    if not args.no_wait:
        _wait_until_ready(base_url, args.timeout)

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
    """Shutdown a running vLLM server process.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed command-line arguments containing PID file path, timeout, and
        force flag. The function reads the PID from the file and sends
        termination signals.

    Returns
    -------
    int
        Exit code: 0 if the server stopped successfully, 1 if the PID file
        is missing, unreadable, or the process did not exit within the timeout.
    """
    if not args.pid_file.exists():
        return 1
    try:
        pid = int(args.pid_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 1

    with suppress(ProcessLookupError):
        os.kill(pid, signal.SIGTERM)
    stopped = _wait_for_exit(pid, args.timeout)
    if not stopped and args.force:
        with suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
        stopped = _wait_for_exit(pid, args.timeout / 2)

    if not stopped:
        return 1

    args.pid_file.unlink(missing_ok=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser for vLLM server management.

    Returns
    -------
    argparse.ArgumentParser
        Configured argument parser with subcommands for "serve-http" and
        "shutdown". The parser includes all necessary options for model
        configuration, server binding, and process management.
    """
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
    serve.add_argument("--no-wait", action="store_true", help="Do not block for readiness.")
    serve.set_defaults(func=cmd_serve_http)

    shut = sub.add_parser("shutdown", help="Stop the running vLLM server.")
    shut.add_argument("--pid-file", type=Path, default=DEFAULT_PID_FILE)
    shut.add_argument("--timeout", type=float, default=10.0)
    shut.add_argument("--force", action="store_true", help="Send SIGKILL if needed.")
    shut.set_defaults(func=cmd_shutdown)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the vLLM server management CLI.

    Parameters
    ----------
    argv : Sequence[str] | None, optional
        Command-line arguments. If None, uses sys.argv. Defaults to None.

    Returns
    -------
    int
        Exit code returned by the selected subcommand (serve-http or shutdown).
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, TimeoutError, OSError):  # pragma: no cover - CLI wrapper
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
