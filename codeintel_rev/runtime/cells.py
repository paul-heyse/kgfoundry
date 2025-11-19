"""Thread-safe runtime cell primitive for mutable subsystems."""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Condition, RLock
from typing import Literal, Protocol, TypeVar, final, runtime_checkable

from codeintel_rev.errors import RuntimeLifecycleError, RuntimeUnavailableError
from codeintel_rev.runtime.factory_adjustment import FactoryAdjuster, NoopFactoryAdjuster
from codeintel_rev.runtime.request_context import capability_stamp_var, session_id_var

T = TypeVar("T")

_SEED_ENV = "KGFOUNDRY_ALLOW_RUNTIME_SEED"
_SEED_GUARD_MESSAGE = (
    "RuntimeCell.seed() is restricted to tests. Use "
    "`allow_runtime_cell_seeding()` or set "
    f"{_SEED_ENV}=1 to override explicitly."
)
_SEED_OVERRIDE = ContextVar("runtime_cell_seed_override", default=False)

InitStatus = Literal["ok", "error"]
CloseStatus = Literal["ok", "error", "noop"]


@dataclass(slots=True, frozen=True)
class RuntimeCellCloseResult:
    """Immutable payload describing close outcome.

    Attributes
    ----------
    cell : str
        Name identifier of the runtime cell that was closed.
    had_payload : bool
        Whether the cell had a payload before closing. True if the cell
        was initialized, False if it was never initialized.
    close_called : bool
        Whether the close() method was actually invoked. False if the
        cell was already closed or never initialized.
    status : CloseStatus
        Close operation status: "ok" for successful close, "error" if an
        exception occurred, "noop" if close was skipped.
    duration_ms : float
        Duration of the close operation in milliseconds.
    error : Exception | None
        Exception raised during close, if any. None if close succeeded
        or was skipped.
    """

    cell: str
    had_payload: bool
    close_called: bool
    status: CloseStatus
    duration_ms: float
    error: Exception | None


@dataclass(slots=True, frozen=True)
class RuntimeCellInitContext:
    """Request-scoped metadata captured during initialization.

    Attributes
    ----------
    session_id : str | None
        Session identifier from request context, if available. Used for
        tracking initialization across request boundaries.
    capability_stamp : str | None
        Capability stamp from request context, if available. Used for
        tracking initialization across capability changes.
    """

    session_id: str | None
    capability_stamp: str | None


@dataclass(slots=True, frozen=True)
class RuntimeCellInitResult:
    """Immutable payload describing initialization outcome.

    Attributes
    ----------
    cell : str
        Name identifier of the runtime cell that was initialized.
    payload : object | None
        Initialized payload object, if initialization succeeded. None if
        initialization failed or was skipped.
    status : InitStatus
        Initialization status: "ok" for successful initialization, "error"
        if an exception occurred.
    duration_ms : float
        Duration of the initialization operation in milliseconds.
    error : Exception | None
        Exception raised during initialization, if any. None if initialization
        succeeded.
    generation : int
        Generation number of this initialization attempt. Increments with
        each initialization cycle.
    context : RuntimeCellInitContext | None
        Request-scoped context captured during initialization, if available.
        Contains session_id and capability_stamp for tracking.
    """

    cell: str
    payload: object | None
    status: InitStatus
    duration_ms: float
    error: Exception | None
    generation: int
    context: RuntimeCellInitContext | None


def _seed_allowed() -> bool:
    """Check if RuntimeCell.seed() is allowed in the current context.

    Returns
    -------
    bool
        True if seeding is allowed via environment variable or context
        override, False otherwise.
    """
    flag = os.getenv(_SEED_ENV, "")
    explicit = flag.strip().lower() in {"1", "true", "yes", "on"}
    return explicit or _SEED_OVERRIDE.get()


@contextmanager
def allow_runtime_cell_seeding() -> Iterator[None]:
    """Temporarily allow RuntimeCell.seed() without env toggles.

    Yields
    ------
    None
        This context manager yields None. While the context is active,
        RuntimeCell.seed() can be called without environment variable toggles.
    """
    token = _SEED_OVERRIDE.set(True)
    try:
        yield
    finally:
        _SEED_OVERRIDE.reset(token)


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
        """Initialize runtime cell.

        Parameters
        ----------
        name : str | None, optional
            Optional name identifier for this cell (for debugging/logging).
        observer : RuntimeCellObserver | None, optional
            Optional observer for lifecycle events.
        max_waiters : int, optional
            Maximum number of concurrent waiters (0 = unlimited).
        wait_timeout_ms : int, optional
            Timeout in milliseconds for wait operations (default: 1500).
        """
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
            in normal operation). Additionally raised when the factory function raises
            RuntimeError during initialization.

        Notes
        -----
        This method implements single-flight initialization: only one thread initializes
        while others wait. It handles cooldown periods after failures and tracks
        generation numbers to detect stale values. Time complexity: O(1) when cached,
        O(init_time) when initialization is needed.

        When a cooldown period is active after a previous initialization failure,
        the original exception from the previous attempt is re-raised via
        ``raise cooldown_error``. The exception type matches the original failure
        (could be RuntimeError, OSError, ImportError, or any other BaseException).
        Callers should handle this to implement retry logic with backoff. Additionally,
        exceptions raised by the factory function during initialization are re-raised
        to preserve the original exception type and stack trace.
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
            When ``True`` (default), disposal errors are suppressed.
            When ``False``, exceptions raised by the payload's disposal propagate.

        Raises
        ------
        AttributeError
            When ``silent=False`` and the payload's close method raises AttributeError
            or when the payload lacks a close method. Re-raised after recording error
            status in the observer.
        OSError
            When ``silent=False`` and the payload's close method raises OSError during
            file/resource cleanup. Re-raised after recording error status in the observer.
        RuntimeError
            When ``silent=False`` and the payload's close method raises RuntimeError
            during runtime state cleanup. Re-raised after recording error status in
            the observer.

        Notes
        -----
        When ``silent`` is ``False`` the payload's ``close`` or cleanup hooks are invoked
        without suppression so exceptions bubble up directly. The default ``silent=True``
        mode catches and swallows all exceptions.

        When ``silent=False`` and an unexpected exception occurs during payload disposal
        (not AttributeError, OSError, or RuntimeError), it is re-raised via ``raise exc``
        to preserve the original exception type and stack trace. This defensive catch-all
        ensures all exceptions propagate correctly when silent mode is disabled. The
        specific exception type is determined by the payload being closed and can be
        any Exception subclass.
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
        """Resolve a disposal function for the given value.

        Parameters
        ----------
        value : T
            Runtime value that may have a close method or context manager
            __exit__ method.

        Returns
        -------
        tuple[Callable[[], None] | None, bool]
            Tuple of (disposer function, close_called flag). If value has
            a close() method, returns (_run_close, True). If value has
            __exit__, returns (_run_exit, False). Otherwise returns (None, False).
        """
        closer = getattr(value, "close", None)
        if callable(closer):
            close_callable = closer

            def _run_close() -> None:
                """Invoke the value's close() method."""
                close_callable()

            return _run_close, True

        exit_fn = getattr(value, "__exit__", None)
        if callable(exit_fn):
            exit_callable = exit_fn

            def _run_exit() -> None:
                """Invoke the value's __exit__ method with None args."""
                exit_callable(None, None, None)

            return _run_exit, False
        return None, False

    def _adjust_factory(self, factory: Callable[[], T]) -> Callable[[], T]:
        """Apply factory adjuster to wrap the factory function.

        Parameters
        ----------
        factory : Callable[[], T]
            Original factory function to adjust.

        Returns
        -------
        Callable[[], T]
            Adjusted factory function, possibly wrapped with tuning hooks.
        """
        return self._adjuster.adjust(cell=self._name, factory=factory)

    @staticmethod
    def _capture_init_context() -> RuntimeCellInitContext | None:
        """Capture request-scoped context variables for initialization.

        Returns
        -------
        RuntimeCellInitContext | None
            Context with session_id and capability_stamp if either is present,
            None if both are absent.
        """
        session_id = session_id_var.get()
        capability_stamp = capability_stamp_var.get()
        if session_id is None and capability_stamp is None:
            return None
        return RuntimeCellInitContext(
            session_id=session_id,
            capability_stamp=capability_stamp,
        )

    def _next_generation_locked(self) -> int:
        """Increment and return the next generation number.

        Returns
        -------
        int
            New generation number after incrementing the counter.
        """
        self._generation_counter += 1
        return self._generation_counter

    def _clear_cooldown_locked(self) -> None:
        """Clear cooldown state after expiry or successful initialization."""
        self._cooldown_until = None
        self._cooldown_error = None

    def _cooldown_error_locked(self, now: float) -> Exception | None:
        """Check if cooldown period is active and return error if so.

        Parameters
        ----------
        now : float
            Current monotonic time for comparison.

        Returns
        -------
        Exception | None
            Cooldown error if cooldown period is active, None if expired
            or not set. Clears cooldown state if expired.
        """
        expiry = self._cooldown_until
        if expiry is None:
            return None
        if expiry <= now:
            self._clear_cooldown_locked()
            return None
        return self._cooldown_error or self._last_error

    def _wait_for_initializer(self, deadline: float) -> None:
        """Wait for another thread to complete initialization.

        Parameters
        ----------
        deadline : float
            Monotonic time deadline for waiting. Raises RuntimeUnavailableError
            if deadline is exceeded.

        Raises
        ------
        RuntimeUnavailableError
            If max waiters limit is exceeded or deadline is exceeded.
        RuntimeLifecycleError
            If initialization failed and last_error is set.
        """
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
        """Execute factory function and handle success/failure.

        Parameters
        ----------
        factory : Callable[[], T]
            Factory function to invoke for initialization.
        generation : int
            Generation number for this initialization attempt.
        context : RuntimeCellInitContext | None
            Request context captured at initialization start.

        Returns
        -------
        T
            Created payload instance from factory.

        Notes
        -----
        Any exception raised by the factory function is re-raised after recording
        the failure in the observer. The exception type matches what the factory
        function raises.
        """
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
        """Update cell state and notify observer after successful initialization.

        Parameters
        ----------
        payload : T
            Successfully created payload instance.
        duration_ms : float
            Initialization duration in milliseconds.
        generation : int
            Generation number for this initialization.
        context : RuntimeCellInitContext | None
            Request context captured at initialization start.
        """
        with self._condition:
            self._value = payload
            self._initialized = True
            self._state = "ready"
            self._last_error = None
            self._value_generation = generation
            self._clear_cooldown_locked()
            self._condition.notify_all()
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
        """Update cell state and notify observer after initialization failure.

        Parameters
        ----------
        exc : Exception
            Exception raised during initialization.
        duration_ms : float
            Initialization duration in milliseconds before failure.
        generation : int
            Generation number for this initialization attempt.
        context : RuntimeCellInitContext | None
            Request context captured at initialization start.
        """
        with self._condition:
            self._value = None
            self._initialized = False
            self._state = "failed"
            self._last_error = exc
            self._condition.notify_all()
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
    "allow_runtime_cell_seeding",
]
