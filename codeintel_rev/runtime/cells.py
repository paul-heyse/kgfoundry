"""Thread-safe runtime cell primitive for mutable subsystems."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import Condition, RLock
from typing import Literal, Protocol, TypeVar, final, runtime_checkable

from codeintel_rev.errors import RuntimeLifecycleError, RuntimeUnavailableError
from codeintel_rev.runtime.factory_adjustment import FactoryAdjuster, NoopFactoryAdjuster
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
    """Thread-safe lazy holder for mutable runtime state with single-flight init."""

    __slots__ = (
        "_adjuster",
        "_condition",
        "_initialized",
        "_last_error",
        "_lock",
        "_max_waiters",
        "_name",
        "_observer",
        "_state",
        "_value",
        "_wait_timeout_s",
        "_waiters",
    )

    def __init__(
        self,
        *,
        name: str | None = None,
        observer: RuntimeCellObserver | None = None,
        max_waiters: int = 32,
        wait_timeout_ms: int = 1500,
    ) -> None:
        self._lock = RLock()
        self._condition = Condition(self._lock)
        self._value: T | None = None
        self._initialized = False
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

        Returns
        -------
        T
            Cached payload instance.
        """
        adjusted_factory = self._adjust_factory(factory)
        deadline = time.monotonic() + (self._wait_timeout_s or 0)
        while True:
            with self._condition:
                if self._state == "ready" and self._value is not None:
                    return self._value
                if self._state == "initializing":
                    self._wait_for_initializer(deadline)
                    continue
                if self._state in {"failed", "empty", "closed"}:
                    self._state = "initializing"
                    break
        return self._run_initializer(adjusted_factory)

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
            self._condition.notify_all()

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
        with self._condition:
            current = self._value
            self._value = None
            self._initialized = False
            self._state = "empty"
            self._last_error = None
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

    def _adjust_factory(self, factory: Callable[[], T]) -> Callable[[], T]:
        return self._adjuster.adjust(cell=self._name, factory=factory)

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

    def _run_initializer(self, factory: Callable[[], T]) -> T:
        start = time.monotonic()
        self._observer.on_init_start(cell=self._name)
        try:
            created = factory()
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            self._handle_init_failure(exc, duration_ms)
            raise
        duration_ms = (time.monotonic() - start) * 1000
        self._handle_init_success(created, duration_ms)
        return created

    def _handle_init_success(self, payload: T, duration_ms: float) -> None:
        with self._condition:
            self._value = payload
            self._initialized = True
            self._state = "ready"
            self._last_error = None
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
            )
        )

    def _handle_init_failure(self, exc: Exception, duration_ms: float) -> None:
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
            )
        )


__all__ = [
    "NullRuntimeCellObserver",
    "RuntimeCell",
    "RuntimeCellCloseResult",
    "RuntimeCellInitResult",
    "RuntimeCellObserver",
]
