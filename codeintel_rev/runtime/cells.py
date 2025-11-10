"""Thread-safe runtime cell primitive for mutable subsystems."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import Literal, Protocol, TypeVar, final, runtime_checkable

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
class RuntimeCellInitResult:
    """Immutable payload describing initialization outcome."""

    cell: str
    payload: object | None
    status: InitStatus
    duration_ms: float
    error: Exception | None


@dataclass(slots=True, frozen=True)
class RuntimeCellCloseResult:
    """Immutable payload describing close outcome."""

    cell: str
    had_payload: bool
    close_called: bool
    status: CloseStatus
    duration_ms: float
    error: Exception | None


def _seed_allowed() -> bool:
    flag = os.getenv(_SEED_ENV, "")
    explicit = flag.strip().lower() in {"1", "true", "yes", "on"}
    return explicit or bool(os.getenv("PYTEST_CURRENT_TEST"))


@runtime_checkable
class RuntimeCellObserver(Protocol):
    """Protocol for observing RuntimeCell lifecycle events."""

    def on_init_start(self, *, cell: str) -> None:  # pragma: no cover - Protocol
        """Invoke before initialization begins."""

    def on_init_end(self, event: RuntimeCellInitResult) -> None:  # pragma: no cover - Protocol
        """Handle completion (success/failure) of initialization."""

    def on_close_end(self, event: RuntimeCellCloseResult) -> None:  # pragma: no cover - Protocol
        """Handle completion (success/failure) of ``close()``."""


class NullRuntimeCellObserver:
    """No-op observer used when instrumentation is disabled."""

    __slots__ = ()

    def on_init_start(self, *, cell: str) -> None:  # pragma: no cover - trivial
        """No-op observer hook."""
        _ = self
        _ = cell

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
    """Thread-safe lazy holder for mutable runtime state.

    Extended Summary
    ----------------
    The cell stores a single payload created on demand via :meth:`get_or_initialize`.
    Test suites can inject fakes via :meth:`seed` when ``PYTEST_CURRENT_TEST`` or
    ``KGFOUNDRY_ALLOW_RUNTIME_SEED=1`` is set. The :meth:`close` method resets the
    cell and best-effort invokes ``close()``/``__exit__`` on the payload. The cell
    uses a reentrant lock to ensure thread-safe initialization and disposal, making
    it suitable for use in multi-threaded environments where runtime resources need
    to be lazily initialized and safely cleaned up.

    Parameters
    ----------
    name : str | None, optional
        Optional identifier used in debug logging and observer callbacks. Defaults
        to ``"runtime"``.
    observer : RuntimeCellObserver | None, optional
        Observer instance that receives lifecycle callbacks (on_init_start,
        on_init_end, on_close_end). Used for instrumentation, monitoring, and
        diagnostics. If None (default), uses NullRuntimeCellObserver which
        suppresses all callbacks. Defaults to None.
    """

    __slots__ = ("_initialized", "_lock", "_name", "_observer", "_value")

    def __init__(
        self,
        *,
        name: str | None = None,
        observer: RuntimeCellObserver | None = None,
    ) -> None:
        self._lock = RLock()
        self._value: T | None = None
        self._initialized = False
        self._name = name or "runtime"
        self._observer: RuntimeCellObserver = observer or NullRuntimeCellObserver()

    def __repr__(self) -> str:
        """
        Return a concise representation without exposing payload internals.

        Returns
        -------
        str
            Debug-friendly representation that omits the payload itself.
        """
        return f"RuntimeCell(name={self._name!r}, initialized={self._initialized})"

    def __bool__(self) -> bool:
        """
        Return ``True`` when the cell currently holds a value.

        Returns
        -------
        bool
            ``True`` if a payload exists; otherwise ``False``.
        """
        return self.peek() is not None

    def peek(self) -> T | None:
        """
        Return the current payload without triggering initialization.

        Returns
        -------
        T | None
            The cached payload if present; otherwise ``None``.
        """
        with self._lock:
            return self._value

    def configure_observer(self, observer: RuntimeCellObserver) -> None:
        """Attach an observer that receives lifecycle callbacks.

        Parameters
        ----------
        observer : RuntimeCellObserver
            Observer instance. May be swapped once during context wiring.
        """
        with self._lock:
            self._observer = observer

    def get_or_initialize(self, factory: Callable[[], T]) -> T:
        """
        Return the payload, invoking ``factory`` exactly once when empty.

        Extended Summary
        ----------------
        This method implements thread-safe lazy initialization using double-checked
        locking. If the cell already contains a payload, it returns immediately.
        Otherwise, it acquires a lock, checks again (to handle race conditions),
        and invokes the factory function to create the payload. The factory is
        called exactly once, even under concurrent access. Observer callbacks are
        invoked before and after initialization, providing instrumentation hooks
        for monitoring and diagnostics.

        Parameters
        ----------
        factory : Callable[[], T]
            Callable that builds the runtime payload. Must be a zero-argument function
            that returns an instance of type T. The factory is invoked only when the
            cell is empty, and its return value is cached for subsequent calls.

        Returns
        -------
        T
            Existing payload if present, otherwise the value returned by ``factory``.
            The payload is cached for subsequent calls, ensuring the factory is
            invoked at most once.

        Raises
        ------
        Exception
            Any exception raised by the factory function is logged with context
            (cell name, exception type, error message) and re-raised to the caller.
            The cell remains in an uninitialized state after a factory failure,
            allowing retry on subsequent calls.

        Notes
        -----
        Time complexity O(1) for cached payload access; O(F) for initialization
        where F is the cost of the factory function. Space complexity O(1) aside
        from the payload itself. The method performs I/O if the factory performs
        I/O (e.g., loading files, establishing network connections). Thread-safe
        due to reentrant lock acquisition. The method is idempotent - multiple
        concurrent calls with the same factory converge to a single initialization.

        Any exception raised by the factory function is logged with context (cell
        name, exception type, error message) and re-raised to the caller. The cell
        remains in an uninitialized state after a factory failure, allowing retry
        on subsequent calls.

        Examples
        --------
        >>> cell = RuntimeCell(name="my-runtime")
        >>> def create_client():
        ...     return MyClient()
        >>> client = cell.get_or_initialize(create_client)
        >>> assert client is not None
        >>> # Subsequent calls return the same instance
        >>> assert cell.get_or_initialize(create_client) is client
        """
        value = self._value
        if value is not None:
            return value

        with self._lock:
            if self._value is not None:
                return self._value
            start = time.monotonic()
            self._observer.on_init_start(cell=self._name)
            try:
                created = factory()
            except Exception as exc:
                duration_ms = (time.monotonic() - start) * 1000
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
                    )
                )
                raise
            self._value = created
            self._initialized = True
            duration_ms = (time.monotonic() - start) * 1000
            LOGGER.debug(
                "runtime_cell_initialized",
                extra={
                    "cell_type": self._name,
                    "payload_type": type(created).__name__,
                    "duration_ms": duration_ms,
                    "status": "ok",
                },
            )
            self._observer.on_init_end(
                RuntimeCellInitResult(
                    cell=self._name,
                    payload=created,
                    status="ok",
                    duration_ms=duration_ms,
                    error=None,
                )
            )
            return created

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

        with self._lock:
            if self._value is not None:
                already_msg = "RuntimeCell is already initialized"
                raise RuntimeError(already_msg)
            self._value = value
            self._initialized = True

    def close(self, *, silent: bool = True) -> None:
        """Clear the payload and attempt to release runtime resources.

        Extended Summary
        ----------------
        This method clears the cell's payload and attempts to release associated
        runtime resources by invoking the payload's ``close()`` method if available.
        When ``silent=True`` (default), any exceptions during disposal are logged
        and suppressed, ensuring cleanup failures don't propagate. When ``silent=False``,
        exceptions are re-raised to allow callers to handle disposal errors explicitly.
        This design supports both defensive cleanup (silent mode) and explicit error
        handling (non-silent mode) depending on the use case.

        Parameters
        ----------
        silent : bool, optional
            When ``True`` (default), disposal errors are logged and suppressed.
            When ``False``, exceptions raised by the payload's disposal propagate
            to the caller. Defaults to True.

        Raises
        ------
        OSError
            When ``silent=False`` and the payload's disposal raises an OS-level error
            (e.g., file handle closure failures). Note: IOError is an alias for OSError
            in Python 3 and is handled by this exception type.
        RuntimeError
            When ``silent=False`` and the payload's disposal raises a runtime error.
        AttributeError
            When ``silent=False`` and the payload's disposal raises an attribute error.
        Exception
            When ``silent=False`` and the payload's disposal raises any other exception
            type. This catch-all handles exceptions from third-party libraries that may
            raise custom exception types during resource disposal. The exception is
            re-raised to the caller after logging.

        Notes
        -----
        Time complexity O(1) for clearing state; O(D) for disposal where D is
        the cost of the payload's close operation. Space complexity O(1).
        The method performs I/O if the payload's close method does I/O (e.g.,
        closing file handles, network connections). Thread-safe due to lock
        acquisition. Idempotent - multiple calls are safe and have no effect
        after the first successful close. The method uses best-effort disposal
        when silent=True, logging warnings for failures without interrupting
        execution flow.

        When ``silent=False``, any exception raised by the payload's disposal
        (including custom exception types from third-party libraries) is re-raised
        to the caller. The specific exception types listed in Raises are the most
        common, but other exception types may also be propagated.
        """
        with self._lock:
            current = self._value
            self._value = None
            self._initialized = False

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
            # Common exceptions from resource disposal (file handles, context managers, etc.)
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
        except Exception as exc:
            # Fallback for other exception types from third-party libraries
            # We cannot know all possible exceptions that payload.close() might raise
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

    @staticmethod
    def _resolve_disposer(value: T) -> tuple[Callable[[], None] | None, bool]:
        closer = getattr(value, "close", None)
        if callable(closer):

            def _run_close() -> None:
                closer()

            return _run_close, True

        exit_fn = getattr(value, "__exit__", None)
        if callable(exit_fn):

            def _run_exit() -> None:
                exit_fn(None, None, None)

            return _run_exit, False
        return None, False


__all__ = [
    "NullRuntimeCellObserver",
    "RuntimeCell",
    "RuntimeCellCloseResult",
    "RuntimeCellInitResult",
    "RuntimeCellObserver",
]
