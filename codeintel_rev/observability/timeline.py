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

        Returns
        -------
        _TimelineScope
            Context manager that emits operation start/end events.
        """
        return _TimelineScope(self, "operation", name, attrs)

    def step(self, name: str, **attrs: object) -> _TimelineScope:
        """Return a context manager that surrounds an internal step.

        Returns
        -------
        _TimelineScope
            Context manager emitting step start/end events.
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

    Returns
    -------
    Timeline
        Timeline configured for the incoming session/run pair.
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


@contextmanager
def bind_timeline(timeline: Timeline | None) -> Iterator[None]:
    """Bind ``timeline`` to the current async/task context.

    Yields
    ------
    None
        Control back to the caller with the timeline bound.
    """
    token = _timeline_var.set(timeline)
    try:
        yield
    finally:
        _timeline_var.reset(token)


__all__ = ["Timeline", "bind_timeline", "current_timeline", "new_timeline"]
