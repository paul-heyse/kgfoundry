"""Hypercorn runner with graceful signal handling.

Exposes helpers so deployments (systemd, tests, dev scripts) can start the
ASGI stack without relying on shell-specific wrappers.
"""

from __future__ import annotations

import asyncio
import os
import signal
from contextlib import suppress
from pathlib import Path
from typing import Awaitable, Callable

from hypercorn.asyncio import serve
from hypercorn.config import Config
from hypercorn.typing import ASGIFramework

from codeintel_rev.app import main as app_main

_DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "ops" / "hypercorn.toml"

ShutdownTrigger = Callable[[], Awaitable[None]]


def _load_config(config_path: str | None = None) -> Config:
    """Return a Hypercorn :class:`Config` from the given TOML path."""
    config = Config()
    raw_path = config_path or os.getenv("HYPERCORN_CONFIG", "")
    path = Path(raw_path) if raw_path else _DEFAULT_CONFIG
    if path.exists():
        config.from_toml(str(path))
    return config


def _build_shutdown_trigger() -> tuple[asyncio.Event, ShutdownTrigger]:
    """Create an asyncio event and shutdown trigger callable."""
    event = asyncio.Event()

    async def _wait_for_shutdown() -> None:
        await event.wait()

    return event, _wait_for_shutdown


async def serve_app(
    asgi: ASGIFramework | None = None,
    *,
    config: Config | None = None,
) -> None:
    """Run Hypercorn with signal-aware shutdown semantics."""
    application = asgi or app_main.asgi
    hypercorn_config = config or _load_config()
    event, trigger = _build_shutdown_trigger()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, event.set)
    await serve(application, hypercorn_config, shutdown_trigger=trigger)


def main() -> None:  # pragma: no cover - convenience shim for CLI usage
    """Execute Hypercorn with the repo default configuration."""
    config = _load_config()
    asyncio.run(serve_app(asgi=app_main.asgi, config=config))


if __name__ == "__main__":  # pragma: no cover
    main()
