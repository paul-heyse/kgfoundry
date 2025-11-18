"""FastAPI/TestClient helper utilities for integration tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from codeintel_rev.app.capabilities import Capabilities
from codeintel_rev.app.config_context import ApplicationContext, ApplicationContextOverrides
from codeintel_rev.mcp_server.server import (
    app_context as mcp_context,
)
from codeintel_rev.mcp_server.server import (
    build_http_app as build_mcp_http_app,
)
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from tests._helpers.settings import build_settings_for_repo, scaffold_repo_root


def build_test_context(
    *,
    repo_root: str | Path,
    context_overrides: ApplicationContextOverrides | None = None,
) -> ApplicationContext:
    """Return an ApplicationContext configured for the provided repo root.

    Parameters
    ----------
    repo_root : str | Path
        Repository root used when resolving settings paths.
    context_overrides : ApplicationContextOverrides | None, optional
        Optional dependency overrides passed to ``ApplicationContext.create`` to
        inject stub dependencies (FAISS manager, VLLM client, etc.).

    Returns
    -------
    ApplicationContext
        Context instance ready for use with FastAPI/TestClient.
    """
    repo_root = Path(repo_root)
    scaffold_repo_root(repo_root)
    settings = build_settings_for_repo(repo_root)
    return ApplicationContext.create(settings=settings, overrides=context_overrides)


def build_test_app(
    context: ApplicationContext,
    *,
    capabilities_override: Capabilities | None = None,
) -> FastAPI:
    """Construct a FastAPI test application backed by the MCP router.

    Parameters
    ----------
    context : ApplicationContext
        Context instance injected into app.state and the MCP contextvar.
    capabilities_override : Capabilities | None, optional
        Capability snapshot to install on ``app.state``. When omitted, the
        helper derives a snapshot from ``context`` via
        :meth:`Capabilities.from_context`.

    Returns
    -------
    FastAPI
        Fully-initialized application ready for ``TestClient`` usage.
    """
    capabilities = capabilities_override or Capabilities.from_context(context)
    mcp_app = build_mcp_http_app(capabilities)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        token = mcp_context.set(context)
        try:
            app.state.context = context
            app.state.capabilities = capabilities
            app.state.capability_stamp = capabilities.stamp()
            await asyncio.sleep(0)
            yield
        finally:
            mcp_context.reset(token)

    app = FastAPI(title="CodeIntel MCP Test App", lifespan=lifespan)

    @app.middleware("http")
    async def _bind_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        token = mcp_context.set(context)
        request.app.state.context = context
        try:
            response = await call_next(request)
        finally:
            mcp_context.reset(token)
        return response

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    app.mount("/mcp", mcp_app)
    return app


@dataclass
class RepoAppHandle:
    """Mutable handle storing a repo-scoped FastAPI test application."""

    repo_root: Path
    app: FastAPI | None = None
    context: ApplicationContext | None = None
    _builder: Callable[[dict[str, object] | None], None] | None = None

    def attach_builder(self, builder: Callable[[dict[str, object] | None], None]) -> None:
        """Install the callable used to rebuild the FastAPI app."""
        self._builder = builder

    def configure(
        self,
        overrides: Mapping[str, object] | None = None,
        **extra_overrides: object,
    ) -> None:
        """Invoke the builder with optional overrides.

        Parameters
        ----------
        overrides : Mapping[str, object] | None, optional
            Mapping of configuration overrides that will be copied before being
            passed to the builder callback.
        **extra_overrides : object
            Additional keyword overrides merged into ``overrides``. Useful for
            quick one-off tweaks such as ``faiss_preload=True`` in tests.

        Raises
        ------
        RuntimeError
            If :meth:`attach_builder` has not been invoked yet.
        """
        if self._builder is None:  # pragma: no cover - defensive
            message = "RepoAppHandle builder not attached"
            raise RuntimeError(message)
        merged: dict[str, object] = {}
        if overrides is not None:
            merged.update(overrides)
        if extra_overrides:
            merged.update(extra_overrides)
        payload: dict[str, object] | None = merged or None
        self._builder(payload)

    def update(self, app: FastAPI, context: ApplicationContext) -> None:
        """Record the latest FastAPI app and context."""
        self.app = app
        self.context = context


__all__ = ["RepoAppHandle", "build_test_app", "build_test_context"]
