"""Shared async dependency injection for MCP adapters."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

from codeintel_rev.app.middleware import get_session_id
from codeintel_rev.mcp_server.scope_utils import get_effective_scope

if TYPE_CHECKING:  # pragma: no cover - typing only
    from codeintel_rev.app.config_context import ApplicationContext
    from codeintel_rev.mcp_server.schemas import ScopeIn

TResult = TypeVar("TResult")


class ToThreadCallable(Protocol[TResult]):
    """Protocol describing ``asyncio.to_thread`` compatible callables."""

    def __call__(
        self,
        func: Callable[..., TResult],
        /,
        *args: object,
        **kwargs: object,
    ) -> Awaitable[TResult]: ...


@dataclass(slots=True, frozen=True)
class AsyncSearchDependencies:
    """Bundle the async primitives adapters rely on.

    Attributes
    ----------
    scope_resolver : Callable[[ApplicationContext, str | None], Awaitable[ScopeIn | None]]
        Async function that resolves scope from application context and optional
        scope identifier. Returns None if scope cannot be resolved.
    session_provider : Callable[[], str | None]
        Function that returns the current session identifier. Returns None if no
        session is active.
    to_thread : ToThreadCallable[Any]
        Function for executing synchronous code in a thread pool. Used for
        running blocking operations asynchronously.
    """

    scope_resolver: Callable[[ApplicationContext, str | None], Awaitable[ScopeIn | None]]
    session_provider: Callable[[], str | None]
    to_thread: ToThreadCallable[Any]


def build_async_dependencies(
    *,
    scope_resolver: Callable[
        [ApplicationContext, str | None], Awaitable[ScopeIn | None]
    ] = get_effective_scope,
    session_provider: Callable[[], str | None] = get_session_id,
    to_thread: ToThreadCallable[Any] = asyncio.to_thread,
) -> AsyncSearchDependencies:
    """Return async dependencies customized for adapter entrypoints.

    Parameters
    ----------
    scope_resolver : Callable[[ApplicationContext, str | None], Awaitable[ScopeIn | None]]
        Coroutine returning the effective scope for a request.
    session_provider : Callable[[], str | None]
        Callable that returns the current session identifier, if any.
    to_thread : ToThreadCallable
        Awaitable helper used to dispatch sync helpers via a threadpool.

    Returns
    -------
    AsyncSearchDependencies
        Frozen dataclass holding the provided dependencies.
    """
    return AsyncSearchDependencies(
        scope_resolver=scope_resolver,
        session_provider=session_provider,
        to_thread=to_thread,
    )


__all__ = ["AsyncSearchDependencies", "build_async_dependencies"]
