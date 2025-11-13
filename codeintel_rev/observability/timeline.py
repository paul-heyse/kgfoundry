"""Lightweight per-session timeline recording utilities."""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import secrets
import threading
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from codeintel_rev.observability.otel import as_span, record_span_event
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)

_timeline_var: contextvars.ContextVar[Timeline | None] = contextvars.ContextVar(
    "codeintel_timeline",
    default=None,
)
_LOG_LOCK = threading.Lock()


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:  # pragma: no cover - defensive
        LOGGER.debug("Invalid float for %s; using default %s", name, default)
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:  # pragma: no cover - defensive
        LOGGER.debug("Invalid integer for %s; using default %s", name, default)
        return default


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


_SAMPLE_RATE = _clamp(_env_float("CODEINTEL_DIAG_SAMPLE", 1.0), 0.0, 1.0)
_MAX_BYTES = max(1024, _env_int("CODEINTEL_DIAG_MAX_BYTES", 10_000_000))


def _diagnostics_dir() -> Path:
    root = Path(os.getenv("CODEINTEL_DIAG_DIR", "./data/diagnostics")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _max_field_len() -> int:
    return max(1, _env_int("CODEINTEL_DIAG_MAX_FIELD_LEN", 256))


class _FlightRecorder:
    """Append-only JSONL recorder with sampling and rotation."""

    __slots__ = ()

    @staticmethod
    def should_sample(*, force: bool = False) -> bool:
        """Determine whether to sample this timeline based on sampling rate.

        Extended Summary
        ----------------
        This method implements probabilistic sampling for timeline events based on
        the configured sampling rate (CODEINTEL_DIAG_SAMPLE environment variable).
        Sampling reduces I/O overhead and storage costs while maintaining statistical
        representativeness. The method uses cryptographically secure random number
        generation to ensure unbiased sampling decisions. Used by new_timeline() to
        determine if a timeline should record events.

        Parameters
        ----------
        force : bool, optional
            If True, forces sampling regardless of sampling rate (default: False).
            Used for debugging and critical paths that must always be recorded.

        Returns
        -------
        bool
            True if this timeline should be sampled (events will be recorded),
            False if sampling should be skipped (events will be discarded). Returns
            True if force=True, True if sampling rate >= 1.0, False if sampling
            rate <= 0.0, otherwise probabilistic based on sampling rate.

        Notes
        -----
        Time complexity O(1) - single random number generation. Space complexity O(1).
        Uses secrets.randbelow() for cryptographically secure random sampling. The
        sampling decision is deterministic per timeline instance (sampled status is
        set once during timeline creation). Sampling rate is clamped to [0.0, 1.0]
        at module load time.
        """
        if force:
            return True
        if _SAMPLE_RATE >= 1.0:
            return True
        if _SAMPLE_RATE <= 0.0:
            return False
        precision = 1_000_000
        threshold = int(_SAMPLE_RATE * precision)
        return secrets.randbelow(precision) < threshold

    @staticmethod
    def _current_file() -> Path:
        stamp = time.strftime("%Y%m%d")
        return _diagnostics_dir() / f"events-{stamp}.jsonl"

    @classmethod
    def _rotate_if_needed(cls, path: Path) -> None:
        if not path.exists():
            return
        try:
            if path.stat().st_size <= _MAX_BYTES:
                return
            rotated = path.with_name(f"{path.stem}-{int(time.time())}.jsonl")
            path.rename(rotated)
        except OSError:  # pragma: no cover - defensive
            LOGGER.debug("Failed to rotate timeline file %s", path, exc_info=True)

    @classmethod
    def write(cls, payload: dict[str, Any]) -> None:
        """Append a JSONL event record to the current timeline file.

        Extended Summary
        ----------------
        This method writes a timeline event to the append-only JSONL file for the
        current date. It performs automatic file rotation when the file exceeds
        MAX_BYTES, ensuring files don't grow unbounded. The method is thread-safe
        using a global lock to prevent concurrent write conflicts. Events are written
        as compact JSON (no whitespace) with UTF-8 encoding. Used by Timeline.event()
        to persist structured observability data.

        Parameters
        ----------
        payload : dict[str, Any]
            Event payload dictionary containing timeline event data. Must be
            JSON-serializable. Common fields include: ts (timestamp), type (event
            type), name (event name), status, session_id, run_id, message, attrs.
            The payload is scrubbed before serialization to prevent PII leakage.

        Notes
        -----
        Time complexity O(n) where n is payload size (JSON serialization + file I/O).
        Space complexity O(n) for JSON string. Performs file I/O with thread-safe
        locking. File rotation is atomic (rename operation). Errors are logged but
        do not propagate (defensive design to prevent timeline failures from affecting
        application). The method uses append mode to ensure events are never lost
        due to concurrent writes.
        """
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        try:
            with _LOG_LOCK:
                path = cls._current_file()
                cls._rotate_if_needed(path)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(data + "\n")
        except OSError:  # pragma: no cover - defensive
            LOGGER.debug("Failed to write timeline event", exc_info=True)


def _scrub_value(value: object) -> object:
    if value is None or isinstance(value, (int, float, bool)):
        result: object = value
    elif isinstance(value, str):
        if len(value) <= _max_field_len():
            result = value
        else:
            digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
            result = {"len": len(value), "sha256": digest}
    elif isinstance(value, bytes):
        digest = hashlib.sha256(value).hexdigest()
        result = {"len": len(value), "sha256": digest}
    elif isinstance(value, Mapping):
        result = {str(key): _scrub_value(val) for key, val in value.items()}
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        result = [_scrub_value(item) for item in value]
    else:
        result = str(value)
    return result


def _scrub_attrs(attrs: Mapping[str, object]) -> dict[str, object]:
    return {str(key): _scrub_value(val) for key, val in attrs.items()}


@dataclass(slots=True, frozen=False)
class Timeline:
    """Append-only JSONL event recorder for a single session/run pair."""

    session_id: str
    run_id: str
    sampled: bool = True

    def event(
        self,
        event_type: str,
        name: str,
        *,
        status: str | None = None,
        message: str | None = None,
        attrs: Mapping[str, object] | None = None,
    ) -> None:
        """Record a structured event."""
        if not self.sampled:
            return
        record: dict[str, object] = {
            "ts": time.time(),
            "type": event_type,
            "name": name,
            "status": status or "ok",
            "session_id": self.session_id,
            "run_id": self.run_id,
        }
        if message:
            record["message"] = message
        if attrs:
            record["attrs"] = _scrub_attrs(attrs)
        _FlightRecorder.write(record)
        try:
            from codeintel_rev.telemetry.reporter import (
                record_timeline_payload as _record_timeline_payload,
            )
        except Exception:  # pragma: no cover - telemetry optional during tests
            _record_timeline_payload = None
        if _record_timeline_payload is not None:
            _record_timeline_payload(record)
        record_span_event(
            f"timeline.{event_type}",
            event_name=name,
            status=status or "ok",
            session_id=self.session_id,
            run_id=self.run_id,
            **(dict(attrs) if attrs else {}),
        )

    def operation(self, name: str, **attrs: object) -> _TimelineScope:
        """Return a context manager that surrounds a root operation.

        Extended Summary
        ----------------
        This method creates a context manager for tracking root-level operations
        (e.g., "search", "index", "publish"). The context manager emits start/end
        events with duration tracking and optional attributes. Used to instrument
        high-level operations in the application.

        Parameters
        ----------
        name : str
            Operation name (e.g., "search", "index.build"). Used in event names
            and telemetry.
        **attrs : object
            Optional keyword arguments to include in operation events as attributes.
            Common attributes include query parameters, result counts, error details.

        Returns
        -------
        _TimelineScope
            Context manager that emits operation start/end events with duration
            tracking. Events are only emitted if the timeline is sampled.

        Notes
        -----
        This method creates a scoped context manager that tracks operation execution.
        Events are emitted at context entry and exit with duration in milliseconds.
        Time complexity: O(1) for scope creation, O(1) for event emission.
        """
        return _TimelineScope(self, "operation", name, attrs)

    def step(self, name: str, **attrs: object) -> _TimelineScope:
        """Return a context manager that surrounds an internal step.

        Extended Summary
        ----------------
        This method creates a context manager for tracking internal steps within
        operations (e.g., "embed", "search", "hydrate"). The context manager emits
        start/end events with duration tracking and optional attributes. Used to
        instrument sub-operations within larger workflows.

        Parameters
        ----------
        name : str
            Step name (e.g., "embed", "search.faiss", "hydrate.duckdb"). Used in
            event names and telemetry.
        **attrs : object
            Optional keyword arguments to include in step events as attributes.
            Common attributes include parameters, result counts, performance metrics.

        Returns
        -------
        _TimelineScope
            Context manager emitting step start/end events with duration tracking.
            Events are only emitted if the timeline is sampled.

        Notes
        -----
        This method creates a scoped context manager that tracks step execution.
        Events are emitted at context entry and exit with duration in milliseconds.
        Steps are nested within operations for hierarchical observability. Time
        complexity: O(1) for scope creation, O(1) for event emission.
        """
        return _TimelineScope(self, "step", name, attrs)


class _TimelineScope:
    """Context manager that emits start/end events with duration."""

    __slots__ = ("_attrs", "_name", "_span", "_start", "_timeline", "_type")

    def __init__(
        self, timeline: Timeline, scope_type: str, name: str, attrs: Mapping[str, object]
    ) -> None:
        self._timeline = timeline
        self._type = scope_type
        self._name = name
        self._attrs = dict(attrs)
        self._start: float | None = None
        self._span: AbstractContextManager[None] = as_span(
            f"{scope_type}:{name}", scope=scope_type, **self._attrs
        )

    def __enter__(self) -> Self:
        if self._timeline.sampled:
            self._start = time.perf_counter()
            self._timeline.event(
                f"{self._type}.start",
                self._name,
                attrs=self._attrs,
            )
        self._span.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        message = str(exc) if exc else None
        status = "error" if exc else "ok"
        duration_ms = None
        if self._timeline.sampled and self._start is not None:
            duration_ms = int(1000 * (time.perf_counter() - self._start))
            extra_attrs: dict[str, object] = dict(self._attrs)
            if duration_ms is not None:
                extra_attrs["duration_ms"] = duration_ms
            self._timeline.event(
                f"{self._type}.end",
                self._name,
                status=status,
                message=message,
                attrs=extra_attrs,
            )
        self._span.__exit__(exc_type, exc, tb)
        return False


def new_timeline(session_id: str | None, *, force: bool = False) -> Timeline:
    """Return a new timeline bound to ``session_id``.

    Extended Summary
    ----------------
    This function creates a new timeline instance for a session, generating a
    unique run identifier and determining sampling status. Timelines provide
    structured event logging and observability for request processing. Used
    during request initialization to create per-request observability context.

    Parameters
    ----------
    session_id : str | None
        Session identifier. If None, uses "anonymous" as the session identifier.
    force : bool, optional
        If True, forces timeline sampling even if sampling rate would normally
        skip this session (default: False). Used for debugging and critical paths.

    Returns
    -------
    Timeline
        Timeline configured for the incoming session/run pair. The timeline has
        a unique run_id and sampled status determined by the flight recorder.

    Notes
    -----
    This function creates a new timeline with a unique run identifier. Sampling
    status is determined by the FlightRecorder based on sampling rate and force
    flag. Time complexity: O(1) for timeline creation.
    """
    session = session_id or "anonymous"
    sampled = _FlightRecorder.should_sample(force=force)
    return Timeline(session_id=session, run_id=uuid.uuid4().hex, sampled=sampled)


def current_timeline() -> Timeline | None:
    """Return the timeline bound to the current context, if any.

    Returns
    -------
    Timeline | None
        Active timeline for the current context, or ``None`` when unset.
    """
    return _timeline_var.get()


def current_or_new_timeline(
    *,
    session_id: str | None = None,
    force: bool = False,
) -> Timeline:
    """Return the active timeline or create a new one when missing.

    Extended Summary
    ----------------
    This function returns the currently active timeline from context, or creates
    a new timeline if none exists. Used as a fallback when timeline access is
    needed but context may not be initialized. Ensures observability is always
    available even when middleware hasn't set up a timeline.

    Parameters
    ----------
    session_id : str | None, optional
        Session identifier to use if creating a new timeline. If None and a new
        timeline is needed, uses "anonymous".
    force : bool, optional
        If True, forces timeline sampling when creating a new timeline (default: False).

    Returns
    -------
    Timeline
        Timeline bound to the request (from context) or a freshly created fallback.
        Always returns a valid timeline instance, never None.

    Notes
    -----
    This function provides a safe way to access timelines when context may not be
    initialized. It checks context variables first, then falls back to creating
    a new timeline. Time complexity: O(1) for context lookup or timeline creation.
    """
    timeline = current_timeline()
    if timeline is not None:
        return timeline
    return new_timeline(session_id, force=force)


@contextmanager
def bind_timeline(timeline: Timeline | None) -> Iterator[None]:
    """Bind ``timeline`` to the current async/task context.

    Extended Summary
    ----------------
    This context manager binds a timeline to the current context variable, making
    it available to `current_timeline()` calls within the context. Used to set
    up timeline context for async operations and background tasks. The timeline
    is automatically unbound when the context exits.

    Parameters
    ----------
    timeline : Timeline | None
        Timeline instance to bind to context. If None, unbinds any existing timeline
        (useful for clearing context).

    Yields
    ------
    None
        Control back to the caller with the timeline bound to context. The timeline
        is available via `current_timeline()` within this context.

    Notes
    -----
    This context manager uses context variables to propagate timelines across async
    boundaries. The timeline is bound at context entry and unbound at exit. Time
    complexity: O(1) for context variable operations.
    """
    token = _timeline_var.set(timeline)
    try:
        yield
    finally:
        _timeline_var.reset(token)


__all__ = ["Timeline", "bind_timeline", "current_timeline", "new_timeline"]
