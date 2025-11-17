"""FastAPI/TestClient helper utilities for integration tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path

from codeintel_rev.app.config_context import ApplicationContext
from codeintel_rev.app.main import build_http_app
from fastapi import FastAPI

from tests._helpers.settings import build_settings_for_repo


def build_test_context(
    *,
    repo_root: str | Path,
    context_overrides: Mapping[str, object] | None = None,
) -> ApplicationContext:
    """Return an ApplicationContext configured for the provided repo root.

    Parameters
    ----------
    repo_root : str | Path
        Repository root used when resolving settings paths.
    context_overrides : Mapping[str, object] | None, optional
        Optional keyword arguments passed to ``ApplicationContext.create`` to
        inject stub dependencies (FAISS manager, VLLM client, etc.).

    Returns
    -------
    ApplicationContext
        Context instance ready for use with FastAPI/TestClient.
    """
    settings = build_settings_for_repo(Path(repo_root))
    overrides = dict(context_overrides or {})
    return ApplicationContext.create(settings=settings, **overrides)


def build_test_app(context: ApplicationContext) -> FastAPI:
    """Construct the FastAPI app using the production router/lifespan stack.

    Parameters
    ----------
    context : ApplicationContext
        Context to install on ``app.state`` during lifespan startup.

    Returns
    -------
    FastAPI
        ASGI application wired with the provided context.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.context = context
        await asyncio.sleep(0)
        yield

    app = build_http_app()
    app.router.lifespan_context = lifespan
    return app
