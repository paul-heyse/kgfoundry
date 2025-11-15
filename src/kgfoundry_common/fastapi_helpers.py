"""Typed FastAPI helper utilities with structured logging and timeouts.

The helpers in this module wrap FastAPI primitives so that dependency injection, middleware, and
exception handlers retain precise type information while also emitting kgfoundry-standard structured
logs and respecting correlation identifiers. All operations enforce a configurable timeout to
prevent runaway tasks inside the request lifecycle.
"""

# [nav:section public-api]

from __future__ import annotations

import asyncio
import time
import typing as t
from collections.abc import Callable
from typing import TYPE_CHECKING, cast

from starlette.middleware.base import BaseHTTPMiddleware

from kgfoundry_common.logging import get_correlation_id, get_logger, with_fields
from kgfoundry_common.navmap_loader import load_nav_metadata
from kgfoundry_common.typing import gate_import

if TYPE_CHECKING:
    from fastapi import Depends, FastAPI, Request
    from fastapi.params import Depends as DependsMarker
    from starlette.requests import Request as StarletteRequest
    from starlette.responses import Response
    from starlette.types import ASGIApp
else:  # pragma: no cover - runtime import guarded
    _fastapi = gate_import("fastapi", "FastAPI helper instrumentation")
    Depends = _fastapi.Depends

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "typed_dependency",
    "typed_exception_handler",
    "typed_middleware",
]
__navmap__ = load_nav_metadata(__name__, tuple(__all__))


# [nav:anchor DEFAULT_TIMEOUT_SECONDS]
DEFAULT_TIMEOUT_SECONDS = 10.0
"""Default timeout applied to FastAPI helpers (in seconds)."""

logger = get_logger(__name__)

MiddlewareFactory = Callable[..., BaseHTTPMiddleware]


async def _await_with_timeout[T](coro: t.Awaitable[T], timeout_seconds: float | None) -> T:
    """Await ``coro`` while respecting ``timeout_seconds`` when provided.

    Parameters
    ----------
    coro : t.Awaitable[T]
        Coroutine to await.
    timeout_seconds : float | None
        Timeout in seconds, or None for no timeout.

    Returns
    -------
    T
        Result of the coroutine.
    """
    if timeout_seconds is None:
        return await coro
    return await asyncio.wait_for(coro, timeout_seconds)


# [nav:anchor typed_dependency]
def typed_dependency[**P, T](
    dependency: Callable[P, t.Awaitable[T]],
    *,
    name: str,
    timeout: float | None = DEFAULT_TIMEOUT_SECONDS,
) -> object:
    """Return a dependency marker suitable for ``Annotated`` parameters.

    The wrapped dependency records structured logs, includes any correlation ID
    stored in :mod:`kgfoundry_common.logging`, and enforces ``timeout``.

    Parameters
    ----------
    dependency : Callable[P, t.Awaitable[T]]
        Dependency function to wrap.
    name : str
        Operation name for logging.
    timeout : float | None, optional
        Timeout in seconds. Defaults to DEFAULT_TIMEOUT_SECONDS.

    Returns
    -------
    object
        Dependency marker for use in Annotated parameters.

    Notes
    -----
    Any exception raised by ``dependency`` is logged and re-raised unchanged.
    """

    async def _instrumented(*args: P.args, **kwargs: P.kwargs) -> T:
        """Instrumented dependency wrapper with logging and timeout.

        Parameters
        ----------
        *args : P.args
            Positional arguments passed to the dependency function.
        **kwargs : P.kwargs
            Keyword arguments passed to the dependency function.

        Returns
        -------
        T
            Result from the dependency function.

        Raises
        ------
        TimeoutError
            If the dependency execution exceeds the timeout.
        Exception
            Any exception raised by the wrapped dependency function is
            propagated unchanged after logging.
        """
        correlation_id = get_correlation_id()
        with with_fields(logger, operation=name, correlation_id=correlation_id) as log:
            start = time.perf_counter()
            log.info("dependency.start", extra={"status": "started"})
            try:
                result = await _await_with_timeout(
                    dependency(*args, **kwargs),
                    timeout_seconds=timeout,
                )
            except TimeoutError:
                duration_ms = (time.perf_counter() - start) * 1000.0
                log.exception(
                    "dependency.timeout",
                    extra={"status": "timeout", "duration_ms": duration_ms},
                )
                raise
            except Exception:  # pragma: no cover - propagated to caller
                duration_ms = (time.perf_counter() - start) * 1000.0
                log.exception(
                    "dependency.error",
                    extra={"status": "error", "duration_ms": duration_ms},
                )
                raise
            duration_ms = (time.perf_counter() - start) * 1000.0
            log.info(
                "dependency.success",
                extra={"status": "success", "duration_ms": duration_ms},
            )
            return result

    marker: DependsMarker = Depends(_instrumented)
    return cast("object", marker)


# [nav:anchor typed_exception_handler]
def typed_exception_handler[E: Exception](
    app: FastAPI,
    exception_type: type[E],
    handler: Callable[[Request, E], t.Awaitable[Response]],
    *,
    name: str,
    timeout: float | None = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Register ``handler`` for ``exception_type`` with logging and timeouts."""

    async def _wrapped(request: Request, exc: E) -> Response:
        """Wrap exception handler with logging and timeout.

        Parameters
        ----------
        request : Request
            FastAPI request object.
        exc : E
            Exception instance to handle.

        Returns
        -------
        Response
            HTTP response from the exception handler.

        Notes
        -----
        Exceptions raised by ``handler`` are logged and re-raised unchanged.

        Raises
        ------
        TimeoutError
            If the handler execution exceeds the timeout.
        Exception
            Any exception raised by the wrapped exception handler is
            propagated unchanged after logging.
        """
        correlation_id = get_correlation_id()
        with with_fields(logger, operation=name, correlation_id=correlation_id) as log:
            start = time.perf_counter()
            exception_name = cast(
                "str",
                getattr(exception_type, "__name__", exception_type.__class__.__name__),
            )
            log.info(
                "exception_handler.start",
                extra={"status": "started", "exception_type": exception_name},
            )
            try:
                result = await _await_with_timeout(
                    handler(request, exc),
                    timeout_seconds=timeout,
                )
            except TimeoutError:
                duration_ms = (time.perf_counter() - start) * 1000.0
                log.exception(
                    "exception_handler.timeout",
                    extra={"status": "timeout", "duration_ms": duration_ms},
                )
                raise
            except Exception:  # pragma: no cover - FastAPI surfaces this
                duration_ms = (time.perf_counter() - start) * 1000.0
                log.exception(
                    "exception_handler.error",
                    extra={"status": "error", "duration_ms": duration_ms},
                )
                raise
            duration_ms = (time.perf_counter() - start) * 1000.0
            log.info(
                "exception_handler.success",
                extra={"status": "success", "duration_ms": duration_ms},
            )
            return result

    handler_callable = cast("Callable[[Request, Exception], t.Awaitable[Response]]", _wrapped)
    app.add_exception_handler(exception_type, handler_callable)


# [nav:anchor typed_middleware]
def typed_middleware(
    app: FastAPI,
    middleware_class: MiddlewareFactory,
    *factory_args: object,
    name: str,
    timeout: float | None = DEFAULT_TIMEOUT_SECONDS,
    **options: object,
) -> None:
    """Register ``middleware_class`` with instrumentation and timeouts."""

    class _InstrumentedMiddleware(BaseHTTPMiddleware):
        """Middleware wrapper that adds logging, metrics, and timeout controls.

        Extended Summary
        ----------------
        Creates an instrumented middleware wrapper that adds structured
        logging, correlation ID tracking, and timeout enforcement to
        the wrapped middleware. The wrapper delegates all request handling
        to the original middleware while recording execution metrics.

        Parameters
        ----------
        app : ASGIApp
            ASGI application instance to wrap.
        """

        def __init__(self, app: ASGIApp) -> None:
            self._delegate = middleware_class(app, *factory_args, **options)
            super().__init__(app)

        async def dispatch(
            self,
            request: StarletteRequest,
            call_next: Callable[[StarletteRequest], t.Awaitable[Response]],
        ) -> Response:
            """Dispatch request through middleware with logging and timeout.

            Parameters
            ----------
            request : StarletteRequest
                Incoming HTTP request.
            call_next : Callable[[StarletteRequest], t.Awaitable[Response]]
                Next middleware or application handler in the chain.

            Returns
            -------
            Response
                HTTP response from the next handler.

            Raises
            ------
            TimeoutError
                If the middleware execution exceeds the timeout.
            Exception
                Any exception raised by the wrapped middleware is
                propagated unchanged after logging.
            """
            correlation_id = get_correlation_id()
            with with_fields(logger, operation=name, correlation_id=correlation_id) as log:
                start = time.perf_counter()
                log.info("middleware.start", extra={"status": "started"})
                try:
                    response = await _await_with_timeout(
                        self._delegate.dispatch(request, call_next),
                        timeout_seconds=timeout,
                    )
                except TimeoutError:
                    duration_ms = (time.perf_counter() - start) * 1000.0
                    log.exception(
                        "middleware.timeout",
                        extra={"status": "timeout", "duration_ms": duration_ms},
                    )
                    raise
                except Exception:  # pragma: no cover - propagated to caller
                    duration_ms = (time.perf_counter() - start) * 1000.0
                    log.exception(
                        "middleware.error",
                        extra={"status": "error", "duration_ms": duration_ms},
                    )
                    raise

                duration_ms = (time.perf_counter() - start) * 1000.0
                log.info(
                    "middleware.success",
                    extra={"status": "success", "duration_ms": duration_ms},
                )
                return response

    name_attr: object = getattr(middleware_class, "__name__", None)
    original_name = name_attr if isinstance(name_attr, str) else middleware_class.__class__.__name__
    _InstrumentedMiddleware.__name__ = original_name
    app.add_middleware(_InstrumentedMiddleware)
