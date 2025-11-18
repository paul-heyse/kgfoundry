"""Hypercorn runner with graceful signal handling.

Exposes helpers so deployments (systemd, tests, dev scripts) can start the
ASGI stack without relying on shell-specific wrappers.
"""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import cast

from hypercorn.asyncio import serve
from hypercorn.config import Config
from hypercorn.typing import ASGIFramework

from codeintel_rev.app import main as app_main

_DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "ops" / "hypercorn.toml"

ShutdownTrigger = Callable[[], Awaitable[None]]


def _load_config(config_path: str | None = None) -> Config:
    """Return a Hypercorn :class:`Config` from the given TOML path.

    Parameters
    ----------
    config_path : str | None, optional
        Optional override path to the Hypercorn TOML file. When omitted,
        falls back to ``HYPERCORN_CONFIG`` or the repo-default path.

    Returns
    -------
    Config
        Config loaded from the resolved TOML path (or defaults when absent).
    """
    config = Config()
    raw_path = config_path or os.getenv("HYPERCORN_CONFIG", "")
    path = Path(raw_path) if raw_path else _DEFAULT_CONFIG
    if path.exists():
        config.from_toml(str(path))
    return config


def _build_shutdown_trigger() -> tuple[asyncio.Event, ShutdownTrigger]:
    """Create an asyncio event and shutdown trigger callable.

    Returns
    -------
    tuple[asyncio.Event, ShutdownTrigger]
        Tuple containing the event to signal shutdown and the trigger callable
        passed to Hypercorn's ``shutdown_trigger`` hook.
    """
    event = asyncio.Event()

    async def _wait_for_shutdown() -> None:
        """Wait for the shutdown event to be set.

        This coroutine blocks until the shutdown event is signaled, at which
        point Hypercorn will gracefully shut down the server.

        Notes
        -----
        Used as the shutdown_trigger callback passed to Hypercorn's serve()
        function. When the event is set (via signal handlers), this coroutine
        completes and Hypercorn initiates graceful shutdown.
        """
        await event.wait()

    return event, _wait_for_shutdown


async def serve_app(
    asgi: ASGIFramework | None = None,
    *,
    config: Config | None = None,
) -> None:
    """Run Hypercorn with signal-aware shutdown semantics."""
    application = asgi or cast("ASGIFramework", app_main.asgi)
    hypercorn_config = config or _load_config()
    event, trigger = _build_shutdown_trigger()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):

            def _set_event(*_: object, _evt: asyncio.Event = event) -> object:
                """Set the shutdown event to trigger graceful shutdown.

                Parameters
                ----------
                *_ : object
                    Ignored signal handler arguments (signum, frame).
                _evt : asyncio.Event, optional
                    Shutdown event to set (defaults to event from closure).

                Returns
                -------
                object
                    Always returns None (required by signal handler signature).

                Notes
                -----
                This function is registered as a signal handler for SIGINT and
                SIGTERM. When called, it sets the shutdown event which causes
                the shutdown trigger coroutine to complete, initiating graceful
                Hypercorn shutdown.
                """
                _evt.set()
                return None

            loop.add_signal_handler(sig, _set_event)
    await serve(application, hypercorn_config, shutdown_trigger=trigger)


def main() -> None:  # pragma: no cover - convenience shim for CLI usage
    """Execute Hypercorn with the repo default configuration."""
    config = _load_config()
    asyncio.run(serve_app(asgi=cast("ASGIFramework", app_main.asgi), config=config))


if __name__ == "__main__":  # pragma: no cover
    main()
