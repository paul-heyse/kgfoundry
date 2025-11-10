"""Thread-safe runtime cell primitive for mutable subsystems."""

from __future__ import annotations

import os
from collections.abc import Callable
from threading import RLock
from typing import TypeVar, final

from kgfoundry_common.logging import get_logger

T = TypeVar("T")

LOGGER = get_logger(__name__)
_SEED_ENV = "KGFOUNDRY_ALLOW_RUNTIME_SEED"
_SEED_GUARD_MESSAGE = (
    f"RuntimeCell.seed() is restricted to tests. Set {_SEED_ENV}=1 to override explicitly."
)


def _seed_allowed() -> bool:
    flag = os.getenv(_SEED_ENV, "")
    explicit = flag.strip().lower() in {"1", "true", "yes", "on"}
    return explicit or bool(os.getenv("PYTEST_CURRENT_TEST"))


@final
class RuntimeCell[T]:
    """Thread-safe lazy holder for mutable runtime state.

    The cell stores a single payload created on demand via :meth:`get_or_initialize`.
    Test suites can inject fakes via :meth:`seed` when ``PYTEST_CURRENT_TEST`` or
    ``KGFOUNDRY_ALLOW_RUNTIME_SEED=1`` is set. The :meth:`close` method resets the
    cell and best-effort invokes ``close()``/``__exit__`` on the payload.

    Parameters
    ----------
    name : str | None, optional
        Optional identifier used in debug logging. Defaults to ``"runtime"``.
    """

    __slots__ = ("_initialized", "_lock", "_name", "_value")

    def __init__(self, *, name: str | None = None) -> None:
        self._lock = RLock()
        self._value: T | None = None
        self._initialized = False
        self._name = name or "runtime"

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

    def get_or_initialize(self, factory: Callable[[], T]) -> T:
        """
        Return the payload, invoking ``factory`` exactly once when empty.

        Parameters
        ----------
        factory : Callable[[], T]
            Callable that builds the runtime payload.

        Returns
        -------
        T
            Existing payload or the value returned by ``factory``.
        """
        value = self._value
        if value is not None:
            return value

        with self._lock:
            if self._value is not None:
                return self._value
            created = factory()
            self._value = created
            self._initialized = True
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
            type from third-party libraries or custom code. This is explicitly re-raised
            via ``raise exc`` to satisfy exception documentation requirements.

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
        """
        with self._lock:
            current = self._value
            self._value = None
            self._initialized = False

        if current is None:
            return

        try:
            self._dispose(current)
        except (OSError, RuntimeError, AttributeError) as exc:
            # Common exceptions from resource disposal (file handles, context managers, etc.)
            if silent:
                LOGGER.warning(
                    "runtime_cell_dispose_failed",
                    extra={"runtime": self._name, "error": str(exc)},
                )
                return
            # Explicitly re-raise the caught exception to satisfy DOC502
            raise exc
        except Exception as exc:
            # Fallback for other exception types from third-party libraries
            # We cannot know all possible exceptions that payload.close() might raise
            if silent:
                LOGGER.warning(
                    "runtime_cell_dispose_failed",
                    extra={"runtime": self._name, "error": str(exc)},
                )
                return
            # Explicitly re-raise the caught exception to satisfy DOC502
            raise exc

    @staticmethod
    def _dispose(value: T) -> None:
        closer = getattr(value, "close", None)
        if callable(closer):
            closer()
            return

        exit_fn = getattr(value, "__exit__", None)
        if callable(exit_fn):
            exit_fn(None, None, None)


__all__ = ["RuntimeCell"]
