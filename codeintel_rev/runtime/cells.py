"""Thread-safe runtime cell primitive for mutable subsystems."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Condition, RLock
from typing import Literal, Protocol, TypeVar, final, runtime_checkable

from codeintel_rev.errors import RuntimeLifecycleError, RuntimeUnavailableError
from codeintel_rev.observability.timeline import Timeline, current_timeline
from codeintel_rev.runtime.factory_adjustment import FactoryAdjuster, NoopFactoryAdjuster
from codeintel_rev.runtime.request_context import capability_stamp_var, session_id_var
from kgfoundry_common.logging import get_logger

T = TypeVar("T")

LOGGER = get_logger(__name__)
_SEED_ENV = "KGFOUNDRY_ALLOW_RUNTIME_SEED"
_SEED_GUARD_MESSAGE = (
    f"RuntimeCell.seed() is restricted to tests. Set {_SEED_ENV}=1 to override explicitly."
)

InitStatus = Literal["ok", "error"]
CloseStatus = Literal["ok", "error", "noop"]


@dataclass(slots=True, frozen=True)
class RuntimeCellCloseResult:
    """Immutable payload describing close outcome."""

    cell: str
    had_payload: bool
    close_called: bool
    status: CloseStatus
    duration_ms: float
    error: Exception | None


@dataclass(slots=True, frozen=True)
class RuntimeCellInitContext:
    """Request-scoped metadata captured during initialization."""

    session_id: str | None
    capability_stamp: str | None
    timeline: Timeline | None


@dataclass(slots=True, frozen=True)
class RuntimeCellInitResult:
    """Immutable payload describing initialization outcome."""

    cell: str
    payload: object | None
    status: InitStatus
    duration_ms: float
    error: Exception | None
    generation: int
    context: RuntimeCellInitContext | None


def _seed_allowed() -> bool:
    flag = os.getenv(_SEED_ENV, "")
    explicit = flag.strip().lower() in {"1", "true", "yes", "on"}
    return explicit or bool(os.getenv("PYTEST_CURRENT_TEST"))


@runtime_checkable
class RuntimeCellObserver(Protocol):
    """Protocol for observing RuntimeCell lifecycle events."""

    def on_init_start(
        self,
        *,
        cell: str,
        generation: int,
        context: RuntimeCellInitContext | None = None,
    ) -> None:  # pragma: no cover - Protocol
        """Invoke before initialization begins."""

    def on_init_end(self, event: RuntimeCellInitResult) -> None:  # pragma: no cover - Protocol
        """Handle completion (success/failure) of initialization."""

    def on_close_end(self, event: RuntimeCellCloseResult) -> None:  # pragma: no cover - Protocol
        """Handle completion (success/failure) of ``close()``."""


class NullRuntimeCellObserver:
    """No-op observer used when instrumentation is disabled."""

    __slots__ = ()

    def on_init_start(
        self,
        *,
        cell: str,
        generation: int,
        context: RuntimeCellInitContext | None = None,
    ) -> None:  # pragma: no cover - trivial
        """No-op observer hook."""
        _ = (self, cell, generation, context)

    def on_init_end(self, event: RuntimeCellInitResult) -> None:  # pragma: no cover - trivial
        """No-op observer hook."""
        _ = self
        _ = event

    def on_close_end(self, event: RuntimeCellCloseResult) -> None:  # pragma: no cover - trivial
        """No-op observer hook."""
        _ = self
        _ = event


@final
class RuntimeCell[T]:
    """Thread-safe lazy holder for mutable runtime state with single-flight init."""

    __slots__ = (
        "_adjuster",
        "_condition",
        "_cooldown_error",
        "_cooldown_until",
        "_generation_counter",
        "_initialized",
        "_last_error",
        "_lock",
        "_max_waiters",
        "_name",
        "_observer",
        "_state",
        "_value",
        "_value_generation",
        "_wait_timeout_s",
        "_waiters",
    )

    def __init__(
        self,
        *,
        name: str | None = None,
        observer: RuntimeCellObserver | None = None,
        max_waiters: int = 0,
        wait_timeout_ms: int = 1500,
    ) -> None:
        self._lock = RLock()
        self._condition = Condition(self._lock)
        self._value: T | None = None
        self._initialized = False
        self._generation_counter = 0
        self._value_generation = 0
        self._cooldown_until: float | None = None
        self._cooldown_error: Exception | None = None
        self._name = name or "runtime"
        self._observer: RuntimeCellObserver = observer or NullRuntimeCellObserver()
        self._state: Literal["empty", "initializing", "ready", "failed", "closed"] = "empty"
        self._last_error: Exception | None = None
        self._max_waiters = max_waiters
        self._wait_timeout_s = max(0, wait_timeout_ms) / 1000.0
        self._waiters = 0
        self._adjuster: FactoryAdjuster = NoopFactoryAdjuster()

    def __repr__(self) -> str:
        """Return a concise representation without exposing payload internals.

        Returns
        -------
        str
            Debug-friendly representation.
        """
        return f"RuntimeCell(name={self._name!r}, state={self._state})"

    def __bool__(self) -> bool:
        """Return ``True`` when the cell currently holds a value.

        Returns
        -------
        bool
            ``True`` when a payload is cached.
        """
        return self.peek() is not None

    def peek(self) -> T | None:
        """Return the cached payload without triggering initialization.

        Returns
        -------
        T | None
            Cached payload when present, otherwise ``None``.
        """
        with self._lock:
            return self._value

    def configure_observer(self, observer: RuntimeCellObserver) -> None:
        """Attach an observer that receives lifecycle callbacks."""
        with self._condition:
            self._observer = observer

    def configure_adjuster(
        self,
        adjuster: FactoryAdjuster,
    ) -> None:
        """Attach a factory adjuster that can wrap the initializer."""
        with self._condition:
            self._adjuster = adjuster

    def get_or_initialize(self, factory: Callable[[], T]) -> T:
        """Return or initialize the payload with single-flight semantics.

        Extended Summary
        ----------------
        This method returns the cached payload if available, or initializes it using
        the provided factory function with single-flight semantics (only one thread
        initializes at a time). It handles cooldown periods, waits for initialization,
        and tracks generation numbers to detect stale values. Used to lazily initialize
        runtime resources (FAISS indexes, hybrid search, etc.) with thread-safe
        caching and error recovery.

        Parameters
        ----------
        factory : Callable[[], T]
            Factory function that creates the payload instance. Called only when
            initialization is needed. The factory is adjusted by the factory adjuster
            before invocation.

        Returns
        -------
        T
            Cached payload instance. The instance is thread-safe and shared across
            all callers until the cell is closed or reset.

        Raises
        ------
        RuntimeError
            Raised when generation tracking becomes inconsistent (defensive check).
            Also raised when the initialization generation is missing (should not occur
            in normal operation).
        Exception
            Any exception stored in the cell from a previous initialization failure
            is re-raised during cooldown periods. The exception is stored in
            `_cooldown_error` (typed as Exception | None) and re-raised via the
            `cooldown_error` variable when cooldown periods are active. The specific
            exception type depends on what was raised during the previous initialization
            attempt (e.g., RuntimeError, RuntimeUnavailableError, RuntimeLifecycleError,
            or any other Exception subclass). The exception is re-raised using
            `raise cooldown_error` where `cooldown_error` is a variable containing the
            stored exception. Note: The exception is re-raised using a variable, so
            pydoclint may flag this as DOC502, but the exception is correctly propagated.

        Notes
        -----
        This method implements single-flight initialization: only one thread initializes
        while others wait. It handles cooldown periods after failures and tracks generation
        numbers to detect stale values. Time complexity: O(1) when cached, O(init_time)
        when initialization is needed.
        """
        adjusted_factory = self._adjust_factory(factory)
        deadline = time.monotonic() + (self._wait_timeout_s or 0)
        context: RuntimeCellInitContext | None = None
        generation: int | None = None
        while True:
            with self._condition:
                now = time.monotonic()
                cooldown_error: BaseException | None = self._cooldown_error_locked(now)
                if cooldown_error is not None:
                    raise cooldown_error
                if self._state == "ready" and self._value is not None:
                    return self._value
                if self._state == "initializing":
                    self._wait_for_initializer(deadline)
                    continue
                if self._state in {"failed", "empty", "closed"}:
                    self._state = "initializing"
                    generation = self._next_generation_locked()
                    context = self._capture_init_context()
                    break
        if generation is None:
            message = "RuntimeCell initialization generation missing"
            raise RuntimeError(message)
        return self._run_initializer(
            adjusted_factory,
            generation=generation,
            context=context,
        )

    def seed(self, value: T) -> None:
        """
        Inject a payload for tests when the cell is empty.

        Parameters
        ----------
        value : T
            Payload instance to cache for subsequent calls.

        Raises
        ------
        RuntimeError
            If seeding is attempted outside a test context or the cell is already
            initialized.
        """
        if not _seed_allowed():
            raise RuntimeError(_SEED_GUARD_MESSAGE)

        with self._condition:
            if self._value is not None:
                message = "RuntimeCell is already initialized"
                raise RuntimeError(message)
            self._value = value
            self._initialized = True
            self._state = "ready"
            self._last_error = None
            self._generation_counter += 1
            self._value_generation = self._generation_counter
            self._condition.notify_all()

    def close(self, *, silent: bool = True) -> None:
        """Clear the payload and attempt to release runtime resources.

        Parameters
        ----------
        silent : bool, optional
            When ``True`` (default), disposal errors are logged and suppressed.
            When ``False``, exceptions raised by the payload's disposal propagate.

        Raises
        ------
        AttributeError
            Propagated when ``silent=False`` and the payload lacks a close method.
        OSError
            Propagated when ``silent=False`` and file/resource cleanup fails.
        RuntimeError
            Propagated when ``silent=False`` and runtime state errors occur.
        Exception
            Any other exception raised by the payload's disposal is propagated when
            ``silent=False``. When ``silent=True`` (default), all exceptions are caught
            and logged.
        """
        with self._condition:
            current = self._value
            self._value = None
            self._initialized = False
            self._state = "empty"
            self._last_error = None
            self._value_generation = 0
            self._clear_cooldown_locked()
            self._condition.notify_all()

        start = time.monotonic()
        if current is None:
            duration_ms = (time.monotonic() - start) * 1000
            LOGGER.debug(
                "runtime_cell_close_noop",
                extra={"cell_type": self._name, "status": "noop"},
            )
            self._observer.on_close_end(
                RuntimeCellCloseResult(
                    cell=self._name,
                    had_payload=False,
                    close_called=False,
                    status="noop",
                    duration_ms=duration_ms,
                    error=None,
                )
            )
            return

        disposer, close_called = self._resolve_disposer(current)
        try:
            if disposer is not None:
                disposer()
        except (OSError, RuntimeError, AttributeError) as exc:
            duration_ms = (time.monotonic() - start) * 1000
            LOGGER.warning(
                "runtime_cell_dispose_failed",
                extra={
                    "cell_type": self._name,
                    "status": "error",
                    "payload_type": type(current).__name__,
                    "error": str(exc),
                },
            )
            self._observer.on_close_end(
                RuntimeCellCloseResult(
                    cell=self._name,
                    had_payload=True,
                    close_called=close_called,
                    status="error",
                    duration_ms=duration_ms,
                    error=exc,
                )
            )
            if silent:
                return
            raise
        except Exception as exc:  # pragma: no cover - defensive
            duration_ms = (time.monotonic() - start) * 1000
            LOGGER.warning(
                "runtime_cell_dispose_failed",
                extra={
                    "cell_type": self._name,
                    "status": "error",
                    "payload_type": type(current).__name__,
                    "error": str(exc),
                },
            )
            self._observer.on_close_end(
                RuntimeCellCloseResult(
                    cell=self._name,
                    had_payload=True,
                    close_called=close_called,
                    status="error",
                    duration_ms=duration_ms,
                    error=exc,
                )
            )
            if silent:
                return
            raise
        else:
            duration_ms = (time.monotonic() - start) * 1000
            LOGGER.debug(
                "runtime_cell_closed",
                extra={
                    "cell_type": self._name,
                    "payload_type": type(current).__name__,
                    "duration_ms": duration_ms,
                    "status": "ok",
                    "close_called": close_called,
                },
            )
            self._observer.on_close_end(
                RuntimeCellCloseResult(
                    cell=self._name,
                    had_payload=True,
                    close_called=close_called,
                    status="ok",
                    duration_ms=duration_ms,
                    error=None,
                )
            )

    def invalidate(self) -> None:
        """Mark the cached payload as stale and schedule lazy re-initialization."""
        self.close()

    def record_failure(self, exc: Exception, ttl_seconds: float) -> None:
        """Cache a failure result to avoid hot-looping initialization attempts."""
        if ttl_seconds <= 0:
            return
        expiry = time.monotonic() + ttl_seconds
        with self._condition:
            self._cooldown_until = expiry
            self._cooldown_error = exc
            self._last_error = exc
            self._state = "failed"
            self._condition.notify_all()

    @staticmethod
    def _resolve_disposer(value: T) -> tuple[Callable[[], None] | None, bool]:
        closer = getattr(value, "close", None)
        if callable(closer):
            close_callable = closer

            def _run_close() -> None:
                close_callable()

            return _run_close, True

        exit_fn = getattr(value, "__exit__", None)
        if callable(exit_fn):
            exit_callable = exit_fn

            def _run_exit() -> None:
                exit_callable(None, None, None)

            return _run_exit, False
        return None, False

    def _adjust_factory(self, factory: Callable[[], T]) -> Callable[[], T]:
        return self._adjuster.adjust(cell=self._name, factory=factory)

    @staticmethod
    def _capture_init_context() -> RuntimeCellInitContext | None:
        session_id = session_id_var.get()
        capability_stamp = capability_stamp_var.get()
        timeline = current_timeline()
        if session_id is None and capability_stamp is None and timeline is None:
            return None
        return RuntimeCellInitContext(
            session_id=session_id,
            capability_stamp=capability_stamp,
            timeline=timeline,
        )

    def _next_generation_locked(self) -> int:
        self._generation_counter += 1
        return self._generation_counter

    def _clear_cooldown_locked(self) -> None:
        self._cooldown_until = None
        self._cooldown_error = None

    def _cooldown_error_locked(self, now: float) -> Exception | None:
        expiry = self._cooldown_until
        if expiry is None:
            return None
        if expiry <= now:
            self._clear_cooldown_locked()
            return None
        return self._cooldown_error or self._last_error

    def _wait_for_initializer(self, deadline: float) -> None:
        if self._max_waiters and self._waiters >= self._max_waiters:
            message = "runtime warming_up"
            raise RuntimeUnavailableError(message, runtime=self._name)
        self._waiters += 1
        try:
            while self._state == "initializing":
                timeout = None
                if self._wait_timeout_s:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        message = "runtime warming_up"
                        raise RuntimeUnavailableError(message, runtime=self._name)
                    timeout = remaining
                self._condition.wait(timeout=timeout)
        finally:
            self._waiters -= 1
        if self._state == "failed" and self._last_error is not None:
            message = f"{self._name} initialization failed"
            raise RuntimeLifecycleError(
                message,
                runtime=self._name,
                cause=self._last_error,
            ) from self._last_error

    def _run_initializer(
        self,
        factory: Callable[[], T],
        *,
        generation: int,
        context: RuntimeCellInitContext | None,
    ) -> T:
        start = time.monotonic()
        self._observer.on_init_start(cell=self._name, generation=generation, context=context)
        try:
            created = factory()
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            self._handle_init_failure(exc, duration_ms, generation, context)
            raise
        duration_ms = (time.monotonic() - start) * 1000
        self._handle_init_success(created, duration_ms, generation, context)
        return created

    def _handle_init_success(
        self,
        payload: T,
        duration_ms: float,
        generation: int,
        context: RuntimeCellInitContext | None,
    ) -> None:
        with self._condition:
            self._value = payload
            self._initialized = True
            self._state = "ready"
            self._last_error = None
            self._value_generation = generation
            self._clear_cooldown_locked()
            self._condition.notify_all()
        LOGGER.debug(
            "runtime_cell_initialized",
            extra={
                "cell_type": self._name,
                "payload_type": type(payload).__name__,
                "duration_ms": duration_ms,
                "status": "ok",
            },
        )
        self._observer.on_init_end(
            RuntimeCellInitResult(
                cell=self._name,
                payload=payload,
                status="ok",
                duration_ms=duration_ms,
                error=None,
                generation=generation,
                context=context,
            )
        )

    def _handle_init_failure(
        self,
        exc: Exception,
        duration_ms: float,
        generation: int,
        context: RuntimeCellInitContext | None,
    ) -> None:
        with self._condition:
            self._value = None
            self._initialized = False
            self._state = "failed"
            self._last_error = exc
            self._condition.notify_all()
        LOGGER.warning(
            "runtime_cell_init_failed",
            extra={
                "cell_type": self._name,
                "status": "error",
                "exc_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        self._observer.on_init_end(
            RuntimeCellInitResult(
                cell=self._name,
                payload=None,
                status="error",
                duration_ms=duration_ms,
                error=exc,
                generation=generation,
                context=context,
            )
        )


__all__ = [
    "NullRuntimeCellObserver",
    "RuntimeCell",
    "RuntimeCellCloseResult",
    "RuntimeCellInitContext",
    "RuntimeCellInitResult",
    "RuntimeCellObserver",
]
