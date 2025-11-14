"""Deterministic execution ledger aligned with OpenTelemetry traces.

This module captures per-request execution data that can be replayed as a
"run report" describing exactly which stages executed, how long they took,
and why a request stopped. The public API mirrors the spec described in
``codeintel_rev/patches/Telemetry_Execution_Ledger.md``: call :func:`begin_run`
from MCP adapters, wrap stage handlers with :func:`step`, emit ad-hoc events
via :func:`record`, and finish with :func:`end_run` to persist the run into the
in-process ring buffer (and optional JSONL sink).
"""

from __future__ import annotations

import contextvars
import json
import os
import textwrap
import time
import uuid
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from contextlib import ContextDecorator
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Any

import msgspec

from codeintel_rev.observability.otel import (
    current_span_id,
    current_trace_id,
    record_span_event,
)
from codeintel_rev.observability.semantic_conventions import Attrs, as_kv
from kgfoundry_common.logging import get_logger

LOGGER = get_logger(__name__)

DEFAULT_STAGE_SEQUENCE: tuple[str, ...] = (
    "request",
    "channel_gather",
    "embed",
    "pool_search",
    "fuse",
    "hydrate",
    "rerank",
    "envelope",
)

_SENSITIVE_REQUEST_KEYS: tuple[str, ...] = (
    "body",
    "query",
    "payload",
    "document",
    "prompt",
    "messages",
)


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        LOGGER.debug("Invalid integer for %s; falling back to %s", name, default)
        return default
    return value if value > 0 else default


@dataclass(slots=True, frozen=True)
class LedgerSettings:
    """Runtime configuration for the execution ledger."""

    enabled: bool = True
    max_runs: int = 512
    flush_path: Path | None = None
    include_request_body: bool = False


class LedgerEntry(msgspec.Struct, frozen=True):
    """Structured record describing a single operation within a run."""

    ts_start: int
    ts_end: int | None
    ok: bool
    stage: str | None
    op: str
    component: str
    attrs: dict[str, object] | None = None
    trace_id: str | None = None
    span_id: str | None = None
    session_id: str | None = None
    run_id: str = ""
    parent_op_id: str | None = None
    op_id: str = ""


class LedgerRun(msgspec.Struct, frozen=True):
    """Complete ledger snapshot for a single MCP request."""

    run_id: str
    session_id: str | None
    tool: str
    request: dict[str, object] | None
    entries: list[LedgerEntry]
    status: str
    stopped_because: str | None
    trace_id: str | None
    root_span_id: str | None
    started_at_ns: int
    completed_at_ns: int
    stage_durations_ms: dict[str, float]
    warnings: list[str]


class ExecutionLedgerStore:
    """Append-only in-process store with optional JSONL persistence."""

    __slots__ = ("_flush_path", "_lock", "_max_runs", "_runs")

    def __init__(self, *, max_runs: int, flush_path: Path | None) -> None:
        self._runs: OrderedDict[str, LedgerRun] = OrderedDict()
        self._lock = RLock()
        self._max_runs = max(1, max_runs)
        self._flush_path = flush_path
        if flush_path is not None:
            flush_path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, run: LedgerRun) -> None:
        """Persist ``run`` into memory (and disk when configured).

        Parameters
        ----------
        run : LedgerRun
            Ledger run object to persist. The run is stored in the in-memory cache
            and optionally appended to the flush_path JSONL file if configured.
            The cache maintains a maximum size limit, evicting oldest runs when
            exceeded.
        """
        with self._lock:
            self._runs[run.run_id] = run
            self._runs.move_to_end(run.run_id)
            while len(self._runs) > self._max_runs:
                self._runs.popitem(last=False)
        if self._flush_path is not None:
            payload = msgspec.to_builtins(run)
            line = json.dumps(payload, ensure_ascii=False)
            try:
                with self._flush_path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except OSError:  # pragma: no cover - best effort sink
                LOGGER.debug("Failed to append ledger run to %s", self._flush_path, exc_info=True)

    def get(self, run_id: str) -> LedgerRun | None:
        """Retrieve a ledger run by identifier.

        Parameters
        ----------
        run_id : str
            Unique identifier for the ledger run to retrieve.

        Returns
        -------
        LedgerRun | None
            The ledger run object if found, or None if the run_id does not exist
            in the store.
        """
        with self._lock:
            return self._runs.get(run_id)

    def latest(self) -> LedgerRun | None:
        """Return the most recently added ledger run.

        Returns
        -------
        LedgerRun | None
            The most recent ledger run (last added to the store), or None if the
            store is empty.
        """
        with self._lock:
            if not self._runs:
                return None
            return next(reversed(self._runs.values()))

    def list_recent(self, limit: int = 20) -> list[LedgerRun]:
        """Return a list of the most recently added ledger runs.

        Parameters
        ----------
        limit : int, optional
            Maximum number of recent runs to return. Defaults to 20. The function
            returns the N most recent runs, ordered from newest to oldest.

        Returns
        -------
        list[LedgerRun]
            List of ledger run objects, ordered from most recent to oldest. The
            list length is at most `limit`, but may be shorter if fewer runs exist.
        """
        with self._lock:
            return list(reversed(list(self._runs.values())[-limit:]))


class _ActiveRun:
    """Mutable run state bound to the current request context."""

    __slots__ = (
        "_ctx_token",
        "_op_stack",
        "_perf_origin_ns",
        "entries",
        "request",
        "root_span_id",
        "run_id",
        "session_id",
        "stage_sequence",
        "started_at_ns",
        "tool",
        "trace_id",
    )

    def __init__(
        self,
        *,
        run_id: str,
        session_id: str | None,
        tool: str,
        request: dict[str, object] | None,
        stage_sequence: Sequence[str],
    ) -> None:
        """Initialize an active ledger run.

        Parameters
        ----------
        run_id : str
            Unique identifier for this run. Used for tracking and retrieval.
        session_id : str | None
            Optional session identifier to group multiple runs together.
        tool : str
            Name of the tool or operation starting this run.
        request : dict[str, object] | None
            Optional request payload to store with the run. May be sanitized
            before storage depending on settings.
        stage_sequence : Sequence[str]
            Expected sequence of execution stages for this run. Used for
            inferring stop reasons and validating execution flow.
        """
        self.run_id = run_id
        self.session_id = session_id
        self.tool = tool
        self.request = request
        self.started_at_ns = time.time_ns()
        self._perf_origin_ns = time.perf_counter_ns()
        self.entries: list[LedgerEntry] = []
        self.trace_id = current_trace_id()
        self.root_span_id = current_span_id()
        self.stage_sequence = tuple(stage_sequence)
        self._op_stack: list[str] = []
        self._ctx_token: contextvars.Token[_ActiveRun | None] | None = None

    def attach(self, token: contextvars.Token[_ActiveRun | None]) -> None:
        """Attach the context variable token for this run.

        Parameters
        ----------
        token : contextvars.Token[_ActiveRun | None]
            Context variable token returned by ContextVar.set(). Stored for
            later use in detach() to reset the context variable.
        """
        self._ctx_token = token

    def detach(self) -> None:
        """Detach this run from the execution context.

        Resets the context variable to its previous value using the stored
        token. This should be called when the run completes or is replaced.
        """
        token = self._ctx_token
        if token is None:
            return
        _RUN_VAR.reset(token)
        self._ctx_token = None

    def monotonic_offset(self) -> int:
        """Return the elapsed time since run start in nanoseconds.

        Returns
        -------
        int
            Elapsed time in nanoseconds since the run was initialized, computed
            using time.perf_counter_ns() for high precision.
        """
        return time.perf_counter_ns() - self._perf_origin_ns

    def new_op_id(self) -> str:
        """Generate a new unique operation identifier.

        Returns
        -------
        str
            Hexadecimal UUID string identifying a new operation within this run.
        """
        return uuid.uuid4().hex

    def push_op(self, op_id: str) -> str | None:
        """Push an operation identifier onto the operation stack.

        Parameters
        ----------
        op_id : str
            Operation identifier to push. The operation becomes the current
            active operation, and its parent (if any) is returned.

        Returns
        -------
        str | None
            The parent operation identifier if the stack was not empty, or None
            if this is the first operation.
        """
        parent = self._op_stack[-1] if self._op_stack else None
        self._op_stack.append(op_id)
        return parent

    def pop_op(self, op_id: str) -> None:
        """Pop an operation identifier from the operation stack.

        Parameters
        ----------
        op_id : str
            Operation identifier to remove. If it's the top of the stack, it's
            popped. Otherwise, it's removed from anywhere in the stack (defensive
            cleanup for out-of-order exits).
        """
        if not self._op_stack:
            return
        if self._op_stack[-1] == op_id:
            self._op_stack.pop()
            return
        try:
            self._op_stack.remove(op_id)
        except ValueError:  # pragma: no cover - defensive cleanup
            return

    def current_parent(self) -> str | None:
        """Return the current parent operation identifier.

        Returns
        -------
        str | None
            The operation identifier at the top of the operation stack (current
            parent), or None if the stack is empty.
        """
        return self._op_stack[-1] if self._op_stack else None

    def append_entry(self, entry: LedgerEntry) -> None:
        """Append a ledger entry to this run.

        Parameters
        ----------
        entry : LedgerEntry
            Ledger entry to append. The entry's trace_id and span_id are used
            to update the run's trace_id and root_span_id if they are not already
            set.
        """
        if entry.trace_id and not self.trace_id:
            self.trace_id = entry.trace_id
        if entry.span_id and not self.root_span_id:
            self.root_span_id = entry.span_id
        self.entries.append(entry)

    def finalize(
        self,
        *,
        status: str | None,
        stop_reason: str | None,
    ) -> LedgerRun:
        """Finalize the run and create an immutable LedgerRun object.

        Parameters
        ----------
        status : str | None
            Optional status string. If None, inferred from entry success rates.
            Status "ok" indicates all entries succeeded, "error" otherwise.
        stop_reason : str | None
            Optional reason for stopping. If None, inferred from entries and
            stage sequence using _infer_stop_reason().

        Returns
        -------
        LedgerRun
            Immutable ledger run object containing all entries, computed metrics,
            stage durations, and warnings. The run is ready for persistence.
        """
        computed_status = status or ("ok" if all(entry.ok for entry in self.entries) else "error")
        derived_stop = stop_reason or _infer_stop_reason(self.entries, self.stage_sequence)
        stage_durations = _stage_durations(self.entries)
        warnings = _collect_warnings(self.entries)
        return LedgerRun(
            run_id=self.run_id,
            session_id=self.session_id,
            tool=self.tool,
            request=self.request,
            entries=list(self.entries),
            status=computed_status,
            stopped_because=derived_stop,
            trace_id=self.trace_id,
            root_span_id=self.root_span_id,
            started_at_ns=self.started_at_ns,
            completed_at_ns=time.time_ns(),
            stage_durations_ms=stage_durations,
            warnings=warnings,
        )


def _sanitize_request(
    payload: Mapping[str, object] | None,
    *,
    include_body: bool,
) -> dict[str, object] | None:
    """Sanitize request payload by redacting sensitive fields.

    Parameters
    ----------
    payload : Mapping[str, object] | None
        Request payload to sanitize. If None, returns None.
    include_body : bool
        If True, includes all fields. If False, redacts fields matching
        sensitive key patterns (e.g., "password", "token", "secret").

    Returns
    -------
    dict[str, object] | None
        Sanitized dictionary with sensitive fields replaced by "<redacted>",
        or None if payload was None or empty.
    """
    if not payload:
        return None
    sanitized: dict[str, object] = {}
    for key, value in payload.items():
        lowered = str(key).lower()
        should_redact = not include_body and any(
            token in lowered for token in _SENSITIVE_REQUEST_KEYS
        )
        sanitized[str(key)] = "<redacted>" if should_redact else value
    return sanitized or None


def _normalize_attrs(attrs: Mapping[str, object] | None) -> dict[str, object] | None:
    """Normalize attributes dictionary by converting keys to strings.

    Parameters
    ----------
    attrs : Mapping[str, object] | None
        Attributes dictionary to normalize. If None or empty, returns None.

    Returns
    -------
    dict[str, object] | None
        Dictionary with all keys converted to strings, or None if attrs was
        None or empty.
    """
    if not attrs:
        return None
    normalized: dict[str, object] = {}
    for key, value in attrs.items():
        normalized[str(key)] = value
    return normalized or None


def _infer_stop_reason(entries: Sequence[LedgerEntry], stage_sequence: Sequence[str]) -> str:
    """Infer the reason a run stopped based on entries and expected stages.

    Parameters
    ----------
    entries : Sequence[LedgerEntry]
        Sequence of ledger entries recorded during the run. Used to determine
        the last stage reached and whether errors occurred.
    stage_sequence : Sequence[str]
        Expected sequence of execution stages. Used to identify which stages
        were not reached.

    Returns
    -------
    str
        Stop reason string indicating why the run stopped. Examples include
        "completed", "no-stages-recorded", "not_reached:stage_name", or
        "stage:error" if an error occurred.
    """
    if not entries:
        return "no-stages-recorded"
    last_entry = entries[-1]
    if not last_entry.ok:
        detail = None
        if last_entry.attrs is not None:
            detail = last_entry.attrs.get("error_type") or last_entry.attrs.get("error")
        reason = str(detail) if detail else "error"
        return f"{(last_entry.stage or last_entry.op)}:{reason}"
    order_map = {stage: idx for idx, stage in enumerate(stage_sequence)}
    seen = {entry.stage for entry in entries if entry.stage in order_map}
    if not seen:
        return "completed"
    highest = max(order_map[stage] for stage in seen)
    for stage in stage_sequence[highest + 1 :]:
        if stage not in seen:
            return f"not_reached:{stage}"
    return "completed"


def _stage_durations(entries: Iterable[LedgerEntry]) -> dict[str, float]:
    """Compute total duration for each execution stage.

    Parameters
    ----------
    entries : Iterable[LedgerEntry]
        Iterable of ledger entries. Entries with stage names and timing
        information are aggregated to compute stage durations.

    Returns
    -------
    dict[str, float]
        Dictionary mapping stage names to total duration in milliseconds.
        Only stages with valid timing information are included.
    """
    durations: dict[str, float] = {}
    for entry in entries:
        if entry.stage is None or entry.ts_end is None:
            continue
        durations.setdefault(entry.stage, 0.0)
        durations[entry.stage] += max(0, entry.ts_end - entry.ts_start) / 1_000_000
    return durations


def _collect_warnings(entries: Iterable[LedgerEntry]) -> list[str]:
    """Collect warning messages from ledger entries.

    Parameters
    ----------
    entries : Iterable[LedgerEntry]
        Iterable of ledger entries. Entries with "warning" or "detail" attributes
        are scanned for warning messages.

    Returns
    -------
    list[str]
        List of warning message strings extracted from entry attributes.
        Duplicate warnings may appear multiple times.
    """
    warnings: list[str] = []
    for entry in entries:
        if not entry.attrs:
            continue
        detail = entry.attrs.get("warning") or entry.attrs.get("detail")
        if detail:
            warnings.append(str(detail))
    return warnings


def _load_settings() -> LedgerSettings:
    """Load ledger settings from environment variables.

    Returns
    -------
    LedgerSettings
        Settings object containing enabled flag, max_runs limit, flush_path
        for persistence, and include_request_body flag. All values are read
        from environment variables with sensible defaults.
    """
    flush_path_str = os.getenv("LEDGER_FLUSH_PATH")
    flush_path = Path(flush_path_str).resolve() if flush_path_str else None
    return LedgerSettings(
        enabled=_env_flag("LEDGER_ENABLED", True),
        max_runs=_env_int("LEDGER_MAX_RUNS", 512),
        flush_path=flush_path,
        include_request_body=_env_flag("LEDGER_INCLUDE_REQUEST_BODY", False),
    )


SETTINGS = _load_settings()
STORE = ExecutionLedgerStore(max_runs=SETTINGS.max_runs, flush_path=SETTINGS.flush_path)
_RUN_VAR: contextvars.ContextVar[_ActiveRun | None] = contextvars.ContextVar(
    "codeintel_execution_ledger", default=None
)


def current_run() -> _ActiveRun | None:
    """Return the active ledger context, if any.

    Returns
    -------
    _ActiveRun | None
        The currently active ledger run bound to the execution context, or None
        if no run is active. The run is retrieved from the context variable
        bound by begin_run().
    """
    return _RUN_VAR.get()


def begin_run(
    *,
    tool: str,
    session_id: str | None,
    run_id: str | None,
    request: Mapping[str, object] | None = None,
    stage_sequence: Sequence[str] | None = None,
) -> str | None:
    """Start a new ledger run and bind it to the current context.

    Parameters
    ----------
    tool : str
        Name of the tool or operation starting this run. Used for categorization
        and filtering in ledger reports.
    session_id : str | None
        Optional session identifier to associate with this run. Sessions group
        multiple runs together for analysis.
    run_id : str | None
        Optional unique identifier for this run. If None, a new UUID is generated.
        The returned run_id can be used to retrieve the run later via get_run().
    request : Mapping[str, object] | None, optional
        Optional request payload to store with the run. The payload is sanitized
        before storage to remove sensitive data unless include_request_body is
        enabled in settings. Defaults to None.
    stage_sequence : Sequence[str] | None, optional
        Optional sequence of stage names defining the expected execution flow.
        If None, uses the default stage sequence. Defaults to None.

    Returns
    -------
    str | None
        The run identifier (provided or generated), or None if ledger tracking
        is disabled via settings. The run is bound to the current execution
        context and can be accessed via current_run().
    """
    if not SETTINGS.enabled:
        return None
    active = current_run()
    if active is not None:
        LOGGER.debug("Ending dangling ledger run %s before starting %s", active.run_id, tool)
        end_run(status="replaced", stop_reason="superseded")
    resolved_id = run_id or uuid.uuid4().hex
    request_payload = _sanitize_request(request, include_body=SETTINGS.include_request_body)
    run = _ActiveRun(
        run_id=resolved_id,
        session_id=session_id,
        tool=tool,
        request=request_payload,
        stage_sequence=stage_sequence or DEFAULT_STAGE_SEQUENCE,
    )
    token = _RUN_VAR.set(run)
    run.attach(token)
    record(
        "run.begin",
        stage="request",
        component="mcp.run",
        **{
            Attrs.MCP_TOOL: tool,
            Attrs.MCP_SESSION_ID: session_id,
            Attrs.MCP_RUN_ID: resolved_id,
        },
    )
    record_span_event(
        "ledger.run.begin",
        **as_kv(
            **{
                Attrs.MCP_TOOL: tool,
                Attrs.MCP_SESSION_ID: session_id,
                Attrs.MCP_RUN_ID: resolved_id,
            }
        ),
    )
    return resolved_id


def end_run(*, status: str | None = None, stop_reason: str | None = None) -> LedgerRun | None:
    """Finalize the current run and persist it into the store.

    Parameters
    ----------
    status : str | None, optional
        Optional status string indicating the run outcome. If the status starts
        with "error", the run is marked as failed. Defaults to None.
    stop_reason : str | None, optional
        Optional reason for stopping the run (e.g., "completed", "cancelled",
        "superseded"). Used for debugging and analysis. Defaults to None.

    Returns
    -------
    LedgerRun | None
        The finalized ledger run object that was persisted, or None if no run
        was active or ledger tracking is disabled. The run is removed from the
        execution context after persistence.
    """
    if not SETTINGS.enabled:
        return None
    run = current_run()
    if run is None:
        return None
    is_ok = not status or not str(status).startswith("error")
    record(
        "run.end",
        stage="envelope",
        component="mcp.run",
        ok=is_ok,
        **{
            Attrs.LEDGER_STATUS: status or ("ok" if is_ok else "error"),
            Attrs.LEDGER_STOP_REASON: stop_reason,
            Attrs.MCP_RUN_ID: run.run_id,
        },
    )
    run.detach()
    result = run.finalize(status=status, stop_reason=stop_reason)
    STORE.save(result)
    record_span_event(
        "ledger.run.end",
        **as_kv(
            **{
                Attrs.MCP_RUN_ID: result.run_id,
                Attrs.MCP_SESSION_ID: result.session_id,
                Attrs.LEDGER_STOP_REASON: result.stopped_because,
                Attrs.LEDGER_STATUS: result.status,
            }
        ),
    )
    return result


class LedgerStep(ContextDecorator):
    """Context manager + decorator that records a ledger entry for a stage."""

    __slots__ = ("_op_id", "_parent", "_start_ns", "attrs", "component", "op", "stage")

    def __init__(
        self,
        *,
        stage: str | None,
        op: str,
        component: str,
        attrs: Mapping[str, object] | None = None,
    ) -> None:
        self.stage = stage
        self.op = op
        self.component = component
        self.attrs = dict(attrs or {})
        self._op_id = uuid.uuid4().hex
        self._start_ns = 0
        self._parent: str | None = None

    def __call__(self, func: Any) -> Any:  # noqa: ANN401 - decorator pattern requires Any
        """Enable LedgerStep to be used as a decorator.

        Parameters
        ----------
        func : Any
            Function to wrap with ledger step tracking. The function is executed
            within a new LedgerStep context manager that records timing and
            execution status.

        Returns
        -------
        Any
            Wrapped function that executes within a ledger step context. The
            wrapper preserves the original function's signature and metadata.
        """

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401 - decorator pattern
            """Execute the original function within a ledger step.

            Parameters
            ----------
            *args : Any
                Positional arguments passed to the original function.
            **kwargs : Any
                Keyword arguments passed to the original function.

            Returns
            -------
            Any
                Return value from the original function.
            """
            fresh = LedgerStep(
                stage=self.stage, op=self.op, component=self.component, attrs=self.attrs
            )
            with fresh:
                return func(*args, **kwargs)

        return wrapper

    def __enter__(self) -> LedgerStep:
        """Enter the ledger step context manager.

        Returns
        -------
        LedgerStep
            Self, bound to the current execution context. The step records its
            start time and emits a span event for observability.
        """
        run = current_run()
        if run is None:
            return self
        self._parent = run.push_op(self._op_id)
        self._start_ns = run.monotonic_offset()
        payload = {
            Attrs.STAGE: self.stage,
            Attrs.COMPONENT: self.component,
            Attrs.OPERATION: self.op,
            **self.attrs,
        }
        record_span_event("ledger.step.start", **as_kv(**payload))
        return self

    def __exit__(self, exc_type, exc, _tb) -> bool:
        """Exit the ledger step context manager.

        Parameters
        ----------
        exc_type : type[BaseException] | None
            Exception type if an exception was raised, or None if the context
            exited normally.
        exc : BaseException | None
            Exception instance if an exception was raised, or None otherwise.
        _tb : TracebackType | None
            Traceback object if an exception was raised. Unused but required by
            the context manager protocol.

        Returns
        -------
        bool
            False to allow exceptions to propagate, True to suppress them. Always
            returns False to ensure exceptions are not suppressed.
        """
        run = current_run()
        if run is None:
            return False
        end_ns = run.monotonic_offset()
        ok = exc_type is None
        attrs = dict(self.attrs)
        if exc_type is not None:
            attrs.setdefault("error_type", exc_type.__name__)
            if exc is not None:
                attrs.setdefault("error", str(exc))
        entry = LedgerEntry(
            ts_start=self._start_ns,
            ts_end=end_ns,
            ok=ok,
            stage=self.stage,
            op=self.op,
            component=self.component,
            attrs=_normalize_attrs(attrs),
            trace_id=current_trace_id(),
            span_id=current_span_id(),
            session_id=run.session_id,
            run_id=run.run_id,
            parent_op_id=self._parent,
            op_id=self._op_id,
        )
        run.append_entry(entry)
        run.pop_op(self._op_id)
        duration_ms = (entry.ts_end - entry.ts_start) / 1_000_000 if entry.ts_end else None
        record_span_event(
            "ledger.step.end",
            **as_kv(
                **{
                    Attrs.STAGE: self.stage,
                    Attrs.COMPONENT: self.component,
                    Attrs.OPERATION: self.op,
                    Attrs.LEDGER_STATUS: "ok" if ok else "error",
                    Attrs.LEDGER_DURATION_MS: duration_ms,
                }
            ),
        )
        return False


def step(
    *,
    stage: str | None,
    op: str,
    component: str,
    **attrs: object,
) -> LedgerStep:
    """Return a :class:`LedgerStep` capturing ``stage`` execution.

    Parameters
    ----------
    stage : str | None
        Optional stage name identifying the execution phase (e.g., "request",
        "search", "hydration"). Used for grouping and filtering ledger entries.
    op : str
        Operation name identifying the specific action being performed (e.g.,
        "faiss.search", "duckdb.query"). Used for detailed tracking.
    component : str
        Component name identifying the subsystem performing the operation
        (e.g., "mcp", "faiss", "duckdb"). Used for categorization.
    **attrs : object
        Additional attributes to attach to the ledger step. These attributes
        are included in ledger entries and span events for observability.

    Returns
    -------
    LedgerStep
        Ledger step context manager that tracks execution timing and status.
        Can be used as a context manager or decorator.
    """
    return LedgerStep(stage=stage, op=op, component=component, attrs=attrs)


def record(
    event_name: str,
    *,
    ok: bool = True,
    stage: str | None = None,
    component: str = "mcp",
    **attrs: object,
) -> None:
    """Record a fine-grained ledger event outside of a context manager.

    Parameters
    ----------
    event_name : str
        Name of the event to record (e.g., "run.begin", "tool.error"). Used as
        the operation name in ledger entries.
    ok : bool, optional
        Whether the event represents a successful operation. If False, the event
        is marked as an error. Defaults to True.
    stage : str | None, optional
        Optional stage name identifying the execution phase. Used for grouping
        and filtering ledger entries. Defaults to None.
    component : str, optional
        Component name identifying the subsystem emitting the event. Defaults
        to "mcp".
    **attrs : object
        Additional attributes to attach to the ledger entry. These attributes
        are included in the entry and span events for observability.
    """
    if not SETTINGS.enabled:
        return
    run = current_run()
    if run is None:
        return
    now = run.monotonic_offset()
    parent = run.current_parent()
    entry = LedgerEntry(
        ts_start=now,
        ts_end=now,
        ok=ok,
        stage=stage,
        op=event_name,
        component=component,
        attrs=_normalize_attrs(attrs),
        trace_id=current_trace_id(),
        span_id=current_span_id(),
        session_id=run.session_id,
        run_id=run.run_id,
        parent_op_id=parent,
        op_id=run.new_op_id(),
    )
    run.append_entry(entry)
    record_span_event(
        "ledger.record",
        **as_kv(
            **{
                Attrs.STAGE: stage,
                Attrs.COMPONENT: component,
                Attrs.OPERATION: event_name,
                Attrs.LEDGER_STATUS: "ok" if ok else "error",
            }
        ),
    )


def get_run(run_id: str) -> LedgerRun | None:
    """Return the stored :class:`LedgerRun` for ``run_id`` when available.

    Parameters
    ----------
    run_id : str
        Unique identifier for the ledger run to retrieve.

    Returns
    -------
    LedgerRun | None
        The ledger run object if found in the store, or None if the run_id does
        not exist or has been evicted from the cache.
    """
    return STORE.get(run_id)


def to_json(run_id: str) -> dict[str, object]:
    """Return a JSON-serializable payload for the specified run.

    Parameters
    ----------
    run_id : str
        Unique identifier for the ledger run to serialize.

    Returns
    -------
    dict[str, object]
        JSON-serializable dictionary containing the run's data, including entries,
        timing information, and metadata. The dictionary can be serialized with
        standard JSON encoders.

    Raises
    ------
    KeyError
        Raised when the run_id does not exist in the store. The error message
        includes the missing run_id for debugging.
    """
    run = STORE.get(run_id)
    if run is None:
        msg = f"Run {run_id} not found"
        raise KeyError(msg)
    return _serialize_run(run)


def to_markdown(run_id: str) -> str:
    """Return Markdown report for the given run identifier.

    Parameters
    ----------
    run_id : str
        Unique identifier for the ledger run to generate a Markdown report for.

    Returns
    -------
    str
        Markdown-formatted report string containing run metadata, entries, and
        execution timeline. The report is suitable for display in documentation
        or markdown viewers.

    Raises
    ------
    KeyError
        Raised when the run_id does not exist in the store. The error is
        propagated from to_json().
    """
    payload = to_json(run_id)
    sections = [
        f"### Run `{payload['run_id']}`",
        "",
        f"*Tool*: `{payload['tool']}`",
        f"*Session*: `{payload.get('session_id') or 'unknown'}`",
        f"*Status*: {payload['status']} ({payload['stopped_because']})",
        "",
        "#### Stage durations (ms)",
    ]
    stage_lines = [
        f"- {stage}: {duration:.2f} ms" for stage, duration in payload["stage_durations_ms"].items()
    ]
    sections.extend(stage_lines or ["- none"])
    sections.append("\n#### Events")
    for entry in payload["entries"]:
        duration_ms = 0.0
        if entry["ts_end"] is not None:
            duration_ms = (entry["ts_end"] - entry["ts_start"]) / 1_000_000
        sections.append(
            textwrap.dedent(
                f"- `{entry['stage'] or entry['op']}` {entry['component']} :: {entry['op']} :: {'ok' if entry['ok'] else 'error'} ({duration_ms:.2f} ms)"
            ).strip()
        )
    return "\n".join(sections)


def _serialize_run(run: LedgerRun) -> dict[str, object]:
    """Serialize a LedgerRun to a JSON-serializable dictionary.

    Parameters
    ----------
    run : LedgerRun
        Ledger run object to serialize. All entries are converted to built-in
        Python types using msgspec.to_builtins().

    Returns
    -------
    dict[str, object]
        Dictionary containing all run fields serialized to JSON-compatible
        types. The dictionary can be serialized with standard JSON encoders.
    """
    entries = [msgspec.to_builtins(entry) for entry in run.entries]
    return {
        "run_id": run.run_id,
        "session_id": run.session_id,
        "tool": run.tool,
        "request": run.request or {},
        "status": run.status,
        "stopped_because": run.stopped_because,
        "trace_id": run.trace_id,
        "root_span_id": run.root_span_id,
        "started_at": datetime.fromtimestamp(run.started_at_ns / 1_000_000_000, tz=UTC).isoformat(),
        "completed_at": datetime.fromtimestamp(
            run.completed_at_ns / 1_000_000_000, tz=UTC
        ).isoformat(),
        "stage_durations_ms": dict(run.stage_durations_ms),
        "warnings": list(run.warnings),
        "entries": entries,
    }


__all__ = [
    "DEFAULT_STAGE_SEQUENCE",
    "ExecutionLedgerStore",
    "LedgerEntry",
    "LedgerRun",
    "LedgerSettings",
    "LedgerStep",
    "begin_run",
    "current_run",
    "end_run",
    "get_run",
    "record",
    "step",
    "to_json",
    "to_markdown",
]
